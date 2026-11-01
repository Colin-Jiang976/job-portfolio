"""静态网站本地检查、更新包和副本恢复；不访问AWS，不覆盖dist。"""
import argparse
from datetime import datetime, timezone, timedelta
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
from urllib.parse import unquote, urlsplit, parse_qs
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / '.local/site-releases'
ALLOWED = {'.html', '.css', '.js', '.json', '.svg', '.webp', '.pdf', '.docx', '.txt', '.ico', '.png'}
MAX_TOTAL = 100 * 1024 * 1024


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def local_path(path):
    path = Path(path).resolve()
    if not path.is_relative_to(LOCAL.resolve()) or path == LOCAL.resolve():
        raise ValueError('输出/恢复目标必须在项目 .local/site-releases 的独立子目录。')
    return path


def safe_name(name):
    path = PurePosixPath(name)
    if (not name or '\\' in name or ':' in name or path.is_absolute() or '..' in path.parts
            or path.as_posix() != name or any(part.startswith('.') for part in path.parts)):
        raise ValueError('更新包包含不安全路径。')
    return path


def source_files(source):
    source = Path(source).resolve(strict=True)
    if not source.is_relative_to(ROOT):
        raise ValueError('检查源须位于当前项目内。')
    result = []
    for directory, dirs, names in os.walk(source, followlinks=False):
        for name in dirs:
            path = Path(directory) / name
            if path.is_symlink() or path.is_junction():
                raise ValueError('不接受目录链接，避免读取选择目录外的内容。')
        for name in names:
            path = Path(directory) / name
            if path.is_symlink() or not path.resolve().is_relative_to(source):
                raise ValueError('不接受指向目录外的文件链接。')
            relative = path.relative_to(source).as_posix()
            safe_name(relative)
            if path.suffix.lower() not in ALLOWED:
                raise ValueError('静态发布不接受此文件类型：' + relative)
            result.append(path)
    if not result or len(result) > 1000 or sum(path.stat().st_size for path in result) > MAX_TOTAL:
        raise ValueError('静态文件为空或超出本工具范围。原JPG不属于此更新包。')
    return sorted(result)


class References(HTMLParser):
    def __init__(self):
        super().__init__()
        self.references = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        for key in ('href', 'src', 'poster'):
            if attrs.get(key):
                self.references.append(attrs[key])


def resolve_reference(source, file, value):
    value = value.strip()
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or not parsed.path or parsed.path.startswith('/api/'):
        return None
    path = unquote(parsed.path)
    target = (source / path.lstrip('/') if path.startswith('/') else file.parent / path).resolve()
    if not target.is_relative_to(source):
        raise ValueError('文件引用超出网站目录：' + value)
    if target.is_dir():
        target /= 'index.html'
    return target


def check_site(source=ROOT / 'dist'):
    source = Path(source).resolve(strict=True)
    files = source_files(source)
    errors = []
    for required in ('index.html', 'content.js', 'app.js', 'photos/index.html', 'invite/index.html', 'log-check/reports.json'):
        if not (source / required).is_file():
            errors.append('缺少必需文件：' + required)
    for file in files:
        if file.suffix.lower() not in {'.html', '.css', '.js', '.json', '.svg', '.txt'}:
            continue
        text = file.read_text(encoding='utf-8-sig')
        relative = file.relative_to(source).as_posix()
        if (re.search(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', text)
                or re.search(r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b', text)
                or re.search(r'CloudFront-Signature=[A-Za-z0-9_~=-]{30,}', text)
                or re.search(r'https?://[^\s<>"\x27]+/invite/[^\s<>"\x27]*#[^\s<>"\x27]{40,}', text)):
            errors.append(relative + ': 疑似混入私钥/访问凭证/完整邀请，不生成更新包')
        references = []
        if file.suffix == '.html':
            parser = References()
            parser.feed(text)
            references = parser.references
        elif file.suffix == '.css':
            references = [match.strip(' \t\r\n\"\x27') for match in re.findall(r'url\(([^)]+)\)', text)]
        if file.suffix == '.json':
            try:
                json.loads(text)
            except ValueError:
                errors.append(relative + ': JSON格式错误')
        for reference in references:
            try:
                target = resolve_reference(source, file, reference)
                if target and not target.is_file():
                    errors.append(relative + ': 引用文件不存在 ' + reference)
                elif target:
                    version = parse_qs(urlsplit(reference).query).get('v', [''])[0]
                    if re.fullmatch(r'[a-f0-9]{12}', version) and sha(target)[:12] != version:
                        errors.append(relative + ': 引用版本与内容哈希不符 ' + reference)
            except ValueError as error:
                errors.append(relative + ': ' + str(error))
    node = shutil.which('node')
    if not node:
        fallback = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
        node = str(fallback) if fallback.is_file() else None
    if not node:
        raise ValueError('未找到Node.js，无法完成JS/三语检查。')
    result = subprocess.run([node, str(ROOT / 'scripts/check_site_content.cjs'), str(source)], capture_output=True,
                            text=True, encoding='utf-8', timeout=30)
    try:
        scripts = json.loads(result.stdout)
    except ValueError as error:
        raise ValueError('JS/三语检查器未能返回结果。') from error
    errors.extend(scripts['errors'])
    for entry in scripts['photoReferences']:
        target = resolve_reference(source, source / entry['source'], entry['url'])
        if target is None or not target.is_file():
            errors.append('首页照片清单引用不存在：' + str(entry['url']))
    return {'ok': not errors, 'errors': errors, 'fileCount': len(files),
            'scriptCount': scripts['scriptCount'], 'languageFiles': scripts['languageFiles']}


def verify_archive(archive):
    archive = Path(archive).resolve(strict=True)
    if not archive.is_relative_to(LOCAL.resolve()):
        raise ValueError('只恢复本项目.local/site-releases中的快照。')
    with zipfile.ZipFile(archive) as package:
        infos = package.infolist()
        if (len({info.filename for info in infos}) != len(infos) or len(infos) > 1001
                or sum(info.file_size for info in infos) > MAX_TOTAL + 1024 * 1024):
            raise ValueError('快照含重复条目或超出恢复范围。')
        manifest = json.loads(package.read('manifest.json'))
        if not isinstance(manifest, dict) or manifest.get('schema') != 'static-site-release-1' or not isinstance(manifest.get('files'), dict):
            raise ValueError('不是本工具生成的静态快照。')
        expected = {'manifest.json'} | {'site/' + name for name in manifest['files']}
        if {info.filename for info in infos} != expected:
            raise ValueError('快照内文件与清单不一致。')
        for name, record in manifest['files'].items():
            safe_name(name)
            if PurePosixPath(name).suffix.lower() not in ALLOWED:
                raise ValueError('快照中包含非静态发布文件。')
            data = package.read('site/' + name)
            if len(data) != record['sizeBytes'] or hashlib.sha256(data).hexdigest() != record['sha256']:
                raise ValueError('快照内容哈希不一致：' + name)
    return manifest


def make_release(source=ROOT / 'dist', *, baseline=None, output=None):
    source = Path(source).resolve(strict=True)
    checked = check_site(source)
    if not checked['ok']:
        raise ValueError('检查未通过：\n' + '\n'.join(checked['errors']))
    previous = verify_archive(Path(baseline) / 'snapshot.zip') if baseline else None
    files = {path.relative_to(source).as_posix(): {'sizeBytes': path.stat().st_size, 'sha256': sha(path)} for path in source_files(source)}
    changed = [name for name in files if previous is None or files[name] != previous['files'].get(name)]
    removed = sorted(set(previous['files']) - set(files)) if previous else []
    stamp = datetime.now(timezone(timedelta(hours=9))).strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]
    output = local_path(output or LOCAL / ('release-' + stamp))
    if output.exists() or output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError('输出已存在或与检查源重叠，不覆盖。')
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.with_name('.incomplete-' + output.name)
    staging.mkdir(exist_ok=False)
    git = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True)
    dirty = subprocess.run(['git', 'status', '--porcelain', '--untracked-files=normal'], cwd=ROOT, capture_output=True, text=True)
    # JS/CSS引用带内容版本参数时，末尾通配符覆盖可能存在的查询串缓存变体。
    invalidations = sorted({'/' + name + ('*' if PurePosixPath(name).suffix in {'.js', '.css'} else '') for name in changed}
                           | ({'/'} if 'index.html' in changed else set()))
    manifest = {'schema': 'static-site-release-1', 'createdAt': datetime.now(timezone.utc).isoformat(),
                'scope': 'static site only; excludes original JPG, database, Lambda, AWS credentials and settings',
                'sourceVersion': {'gitHead': git.stdout.strip() if git.returncode == 0 else None,
                                  'hasLocalChanges': bool(dirty.stdout.strip()), 'exactVersionIsFileHashes': True},
                'files': files, 'changedFiles': sorted(changed), 'removedFilesNotApplied': removed,
                'invalidationPaths': invalidations, 'baselineIsAwsVerification': False, 'checks': checked}
    write_json(staging / 'manifest.json', manifest)
    with zipfile.ZipFile(staging / 'snapshot.zip', 'x', zipfile.ZIP_DEFLATED) as snapshot, \
         zipfile.ZipFile(staging / 'update.zip', 'x', zipfile.ZIP_DEFLATED) as update:
        snapshot.write(staging / 'manifest.json', 'manifest.json')
        for name, record in files.items():
            data = (source / name).read_bytes()
            if hashlib.sha256(data).hexdigest() != record['sha256']:
                raise ValueError('打包期间源文件变化，批次未完成。')
            snapshot.writestr('site/' + name, data)
            if name in changed:
                update.writestr(name, data)
    write_json(staging / 'invalidation-paths.json', {'Paths': {'Quantity': len(invalidations), 'Items': invalidations}})
    (staging / 'README.txt').write_text(
        f'静态网站本地材料：{len(files)}文件，本次更新{len(changed)}文件。\n'
        'update.zip内部为桶根相对路径；解压后只上传这些变更文件。\n'
        'snapshot.zip用于本地副本恢复，不直接上传其site/或manifest.json到网站。\n'
        'manifest.json保存哈希、检查与源版本；invalidation-paths.json列缓存失效路径。\n'
        '不自动上传/删除/失效，不包含数据库、原JPG、Lambda或登录凭证。\n'
        '本地恢复不等于云端回滚；云端恢复仍须本人上传旧文件及按范围失效。\n', encoding='utf-8')
    staging.rename(output)
    verify_archive(output / 'snapshot.zip')
    stage_upload(output)
    return output


def stage_upload(directory):
    directory = local_path(directory)
    manifest = verify_archive(directory / 'snapshot.zip')
    upload = directory / 'upload'
    if upload.is_symlink() or upload.is_junction() or not upload.resolve().is_relative_to(directory):
        raise ValueError('上传目录不能通过链接指向发布目录外。')
    upload.mkdir(exist_ok=True)
    existing = {path.relative_to(upload).as_posix() for path in source_files(upload)} if any(upload.iterdir()) else set()
    if existing - set(manifest['changedFiles']):
        raise ValueError('上传目录有不属于本次变更的文件，拒绝混入更新包。')
    with zipfile.ZipFile(directory / 'update.zip') as package:
        if set(package.namelist()) != set(manifest['changedFiles']) or len(package.namelist()) != len(manifest['changedFiles']):
            raise ValueError('更新ZIP与变更清单不一致。')
        for name in manifest['changedFiles']:
            safe_name(name)
            target = upload / name
            if not target.resolve().is_relative_to(upload.resolve()):
                raise ValueError('上传文件路径超出本批目录。')
            data = package.read(name)
            if hashlib.sha256(data).hexdigest() != manifest['files'][name]['sha256']:
                raise ValueError('更新文件内容与清单不一致。')
            if target.exists() and target.read_bytes() != data:
                raise ValueError('上传材料中已有不同内容，拒绝覆盖。')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    return upload


def restore(archive, output):
    manifest = verify_archive(archive)
    output = local_path(output)
    if output.exists():
        raise ValueError('恢复只接受尚不存在的新目录，不覆盖dist或已有文件。')
    output.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive) as package:
        for name in manifest['files']:
            path = output / safe_name(name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(package.read('site/' + name))
    checked = check_site(output)
    if not checked['ok']:
        raise ValueError('恢复副本检查未通过；副本保留，不影响原网站。')
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    check = sub.add_parser('check')
    check.add_argument('--source', type=Path, default=ROOT / 'dist')
    build = sub.add_parser('build')
    build.add_argument('--source', type=Path, default=ROOT / 'dist')
    build.add_argument('--baseline', type=Path)
    build.add_argument('--output', type=Path)
    build.add_argument('--open', action='store_true', help='成功后打开结果文件夹')
    recovery = sub.add_parser('restore')
    recovery.add_argument('archive', type=Path)
    recovery.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        if args.action == 'check':
            result = check_site(args.source)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result['ok'] else 1
        if args.action == 'build':
            baseline = args.baseline
            reference = LOCAL / 'published-reference.json'
            if baseline is None and reference.is_file():
                baseline = local_path(read_json(reference)['directory'])
            output = make_release(args.source, baseline=baseline, output=args.output)
            write_json(LOCAL / 'latest-prepared.json', {'directory': str(output), 'status': 'prepared-local-only'})
            print('本地更新材料已准备：' + str(output))
            if args.open:
                os.startfile(str(output))
        else:
            print('已恢复到本地新副本：' + str(restore(args.archive, args.output)))
        return 0
    except (ValueError, OSError, KeyError, zipfile.BadZipFile, subprocess.SubprocessError) as error:
        print('未完成：' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
