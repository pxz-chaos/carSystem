(function () {
  async function compressFile(file, maxSide, quality) {
    if (!file || !file.type || !file.type.startsWith('image/')) return file;
    if (file.size < 450 * 1024) return file;

    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height));
    if (scale >= 0.999 && file.size < 1200 * 1024) return file;

    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(bitmap.width * scale));
    canvas.height = Math.max(1, Math.round(bitmap.height * scale));
    const ctx = canvas.getContext('2d');
    ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);

    const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', quality));
    if (!blob || blob.size >= file.size) return file;
    const name = (file.name || 'upload.jpg').replace(/\.[^.]+$/, '') + '.jpg';
    return new File([blob], name, { type: 'image/jpeg', lastModified: Date.now() });
  }

  async function replaceInputFile(input, file) {
    const dt = new DataTransfer();
    dt.items.add(file);
    input.files = dt.files;
  }

  document.addEventListener('submit', async function (ev) {
    const form = ev.target;
    if (!form || !form.querySelectorAll) return;
    const inputs = form.querySelectorAll('input[type="file"][data-compress-image]');
    if (!inputs.length || form.dataset.compressing === '1') return;

    ev.preventDefault();
    form.dataset.compressing = '1';

    const btn = form.querySelector('button[type="submit"], button:not([type])');
    const oldText = btn ? btn.innerText : '';
    if (btn) {
      btn.disabled = true;
      btn.innerText = '正在压缩图片并识别，请稍候...';
    }

    try {
      for (const input of inputs) {
        if (!input.files || !input.files[0]) continue;
        const compressed = await compressFile(input.files[0], 1280, 0.82);
        if (compressed !== input.files[0]) await replaceInputFile(input, compressed);
      }
      form.submit();
    } catch (err) {
      console.warn('image compression skipped:', err);
      if (btn) {
        btn.disabled = false;
        btn.innerText = oldText;
      }
      form.dataset.compressing = '0';
      form.submit();
    }
  }, true);
})();
