// 照片应用的界面文字。照片标题来自接口，原求职文案文件保持独立。
window.PHOTO_TEXT = {
  ja: {
    pageTitle: '写真 | Cloud & Nature', skip: '本文へ移動', photoNumber: '写真 {number}', previewTitle: '写真のプレビュー',
    title: '写真を見て、原寸でダウンロード。',
    intro: '自分で撮影し、仕上げた写真です。プレビューで選んで、元のサイズの JPG を保存できます。',
    albumTitle: '写真コレクション', localNotice: 'ローカル動作確認用です。AWS のデータベース・招待認証には接続していません。',
    loading: '写真を読み込んでいます。', loaded: '{start}–{end} 枚目を表示', page: '{page} ページ',
    empty: '現在、表示できる写真はありません。', previous: '前のページ', next: '次のページ',
    preview: '大きく見る：{title}', download: 'JPG をダウンロード', close: '閉じる', retry: 'もう一度読み込む',
    downloadStarted: 'ダウンロードを開始します。保存先と完了状況はブラウザーで確認してください。',
    downloadNote: 'ダウンロードは元サイズの JPG です。保存先や完了状況はブラウザーで確認してください。',
    invitationRequired: '招待の有効期限が切れているか、アクセスを確認できません。共有された招待リンクから開き直してください。',
    unavailable: '写真を読み込めませんでした。少し待ってから、もう一度お試しください。',
    invalidCursor: 'ページ情報が無効です。もう一度読み込むと、最初のページに戻ります。',
    imageError: 'プレビュー画像を読み込めません。', back: 'ポートフォリオへ戻る'
  },
  zh: {
    pageTitle: '照片 | Cloud & Nature', skip: '跳转到正文', photoNumber: '照片 {number}', previewTitle: '照片预览',
    title: '浏览照片，下载原尺寸 JPG。',
    intro: '这里是我拍摄并修图后的作品。先看预览，再保存原尺寸的 JPG 文件。',
    albumTitle: '照片相册', localNotice: '这是本地功能验证，尚未连接 AWS 数据库或验证云端邀请权限。',
    loading: '正在读取照片。', loaded: '当前显示第 {start}–{end} 张', page: '第 {page} 页',
    empty: '目前没有可显示的照片。', previous: '上一页', next: '下一页',
    preview: '查看大图：{title}', download: '下载原 JPG', close: '关闭', retry: '重新读取',
    downloadStarted: '已请求开始下载，请在浏览器中确认保存位置和完成状态。',
    downloadNote: '下载文件是原尺寸 JPG。请在浏览器中确认保存位置和下载结果。',
    invitationRequired: '邀请可能已过期，或当前访问未获准。请重新打开收到的完整邀请链接。',
    unavailable: '暂时无法读取照片，请稍后重试。',
    invalidCursor: '翻页信息无效，重新读取将返回第一页。',
    imageError: '预览图读取失败。', back: '返回求职网站'
  },
  en: {
    pageTitle: 'Photography | Cloud & Nature', skip: 'Skip to content', photoNumber: 'Photograph {number}', previewTitle: 'Photo preview',
    title: 'Explore the photographs. Keep the full-size JPG.',
    intro: 'Photographs I have taken and edited. Explore the previews, then save the original-size JPG files.',
    albumTitle: 'Photo collection', localNotice: 'Local function check. AWS database access and cloud invitation permissions have not been verified here.',
    loading: 'Loading photographs.', loaded: 'Showing {start}–{end}', page: 'Page {page}',
    empty: 'There are no photographs to display yet.', previous: 'Previous', next: 'Next',
    preview: 'Open preview: {title}', download: 'Download original JPG', close: 'Close', retry: 'Try again',
    downloadStarted: 'Download requested. Check your browser for the save location and completion status.',
    downloadNote: 'Downloads are original-size JPG files. Check your browser for the save location and download result.',
    invitationRequired: 'Your invitation may have expired, or access could not be verified. Reopen the complete invitation link you received.',
    unavailable: 'The photographs could not be loaded. Please try again shortly.',
    invalidCursor: 'The page information is invalid. Try again to return to the first page.',
    imageError: 'The preview could not be loaded.', back: 'Back to portfolio'
  }
};
