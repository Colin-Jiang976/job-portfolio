(() => {
  const grid = document.querySelector('#photos'), status = document.querySelector('#status');
  const place = document.querySelector('#place'), apply = document.querySelector('#apply'), save = document.querySelector('#save');
  const preview = document.querySelector('#preview');
  let data, selected = new Set(), assignments = {}, dirty = false, revision = 0;
  function updateSelection() {
    document.querySelector('#selection-count').textContent = `已选 ${selected.size} 张`;
    apply.disabled = !selected.size;
    grid.querySelectorAll('.photo').forEach(card => {
      const checked = selected.has(card.dataset.id);
      card.classList.toggle('selected', checked); card.querySelector('input').checked = checked;
    });
  }
  function updateLabels() {
    const counts = new Map();
    for (const photo of data.photos) {
      const label = assignments[photo.id] || '未分类';
      counts.set(label, (counts.get(label) || 0) + 1);
      const card = [...grid.children].find(node => node.dataset.id === photo.id);
      card.querySelector('.location').textContent = '地点：' + label;
    }
    document.querySelector('#summary').textContent = `共 ${data.photos.length} 张 · ` + [...counts].map(([label, count]) => `${label} ${count} 张`).join(' · ');
    if (data.requireLocations) {
      const remaining = Object.values(assignments).filter(value => !value).length;
      save.textContent = remaining ? `保存分组进度（还剩 ${remaining} 张）` : '保存地点并完成准备';
      document.querySelector('#save-note').textContent = remaining ? '可以中途保存；全部照片选好地点后才能发布。' : '地点已齐全，保存后即可回维护菜单发布。';
    }
  }
  document.querySelector('#select-all').addEventListener('click', () => { selected = new Set(data.photos.map(p => p.id)); updateSelection(); });
  document.querySelector('#clear-selection').addEventListener('click', () => { selected.clear(); updateSelection(); });
  document.querySelector('#add-place').addEventListener('click', () => {
    const input = document.querySelector('#new-place'); const label = input.value.trim().normalize('NFC');
    if (!label || ['未分类','未分類','unassigned'].includes(label) || [...label].length > 60 || /\p{C}/u.test(label)) { status.textContent = '请填写60字以内的实际地点名称。'; return; }
    let option = [...place.options].find(row => row.value === label);
    if (!option) { option = document.createElement('option'); option.value = label; option.textContent = label; place.append(option); }
    place.value = label; input.value = ''; status.textContent = `已选择“${label}”，勾选照片后点击应用。`;
  });
  apply.addEventListener('click', () => {
    const count = selected.size;
    for (const id of selected) assignments[id] = place.value;
    selected.clear(); dirty = true; revision++; save.textContent = '保存本地清单';
    updateSelection(); updateLabels(); status.textContent = `已将 ${count} 张照片分到“${place.value || '未分类'}”。继续分组，最后保存。`;
  });
  save.addEventListener('click', async () => {
    save.disabled = true; status.textContent = '正在保存本地清单。';
    const savingRevision = revision;
    try {
      const response = await fetch('api/save', {method:'POST',headers:{'Content-Type':'application/json','X-Photo-Picker':'local-save'},
        body:JSON.stringify({baselineHash:data.baselineHash,assignments})});
      const result = await response.json();
      if (!response.ok || !result.saved) throw new Error(result.error || '保存失败，请重试。');
      data.baselineHash = result.baselineHash;
      dirty = revision !== savingRevision; save.textContent = dirty ? '保存本地清单' : '再次保存本地清单';
      status.textContent = dirty ? '上一份清单已保存，但还有刚才的新修改，请再次保存。' : data.requireLocations ?
        (result.complete ? `本批 ${result.preparedCount} 张地点已齐全，发布材料准备完成。尚未上传。请回聊天回复“新照片分组已保存”。` : `分组进度已保存，还剩 ${result.remaining} 张需要选择地点。`) :
        `已保存 ${result.count} 张照片的地点清单。没有上传，也没有修改 AWS。请回聊天回复“分组已保存”。`;
    } catch (error) { status.textContent = error.message || '保存失败，请重试。'; }
    finally { save.disabled = false; }
  });
  document.querySelector('#close-preview').addEventListener('click', () => preview.close());
  window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
  async function start() {
    try {
      const response = await fetch('api/catalog', {cache:'no-store'});
      if (!response.ok) throw new Error('本地会话已关闭，请从维护菜单重新打开。');
      data = await response.json();
      if (data.requireLocations) {
        document.querySelector('#title').textContent = '新照片：批量选择地点';
        document.querySelector('#intro').textContent = '勾选同一地点的照片，一次应用地点。可以中途保存；全部选好地点后，保存即完成本地准备，不用逐张输入。';
      }
      for (const label of ['', ...data.places]) {
        const option = document.createElement('option'); option.value = label; option.textContent = label || '未分类'; place.append(option);
      }
      for (const photo of data.photos) {
        assignments[photo.id] = photo.location;
        const card = document.createElement('article'); card.className = 'photo'; card.dataset.id = photo.id;
        if (photo.preview) {
          const button = document.createElement('button'); button.type = 'button'; button.className = 'image-button'; button.setAttribute('aria-label', '查看大图 ' + photo.filename);
          const img = document.createElement('img'); img.src = photo.preview; img.alt = photo.filename; button.append(img);
          button.addEventListener('click', () => {
            const image = document.querySelector('#preview-image'); image.src = photo.preview; image.alt = photo.filename;
            document.querySelector('#preview-caption').textContent = photo.filename; preview.showModal();
          });
          card.append(button);
        } else { const missing = document.createElement('div'); missing.className = 'missing'; missing.textContent = '本地预览缺失'; card.append(missing); }
        const label = document.createElement('label'), checkbox = document.createElement('input'); checkbox.type = 'checkbox';
        checkbox.addEventListener('change', () => { if (checkbox.checked) selected.add(photo.id); else selected.delete(photo.id); updateSelection(); });
        label.append(checkbox, document.createTextNode(photo.filename));
        const current = document.createElement('p'); current.className = 'location'; card.append(label,current); grid.append(card);
      }
      updateLabels(); updateSelection();
      document.querySelector('#select-all').disabled = false; document.querySelector('#clear-selection').disabled = false; place.disabled = false; save.disabled = false;
      status.textContent = '勾选同一地点的照片，在上方选择地点并应用。点击图片可放大。';
    } catch(error) { status.textContent = error.message || '本地照片读取失败。'; }
  }
  start();
})();
