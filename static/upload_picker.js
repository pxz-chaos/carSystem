(function () {
  function filenameOf(input) {
    if (!input.files || !input.files.length) return '';
    return input.files[0].name || '已选择照片';
  }

  document.addEventListener('change', function (event) {
    const input = event.target;
    if (!input.matches || !input.matches('input[type="file"][data-upload-picker]')) return;

    const form = input.form;
    if (!form) return;

    // Only keep the most recently selected source, otherwise the backend may
    // receive both camera and gallery files.
    form.querySelectorAll('input[type="file"][data-upload-picker]').forEach(function (other) {
      if (other !== input) other.value = '';
    });

    const nameBox = form.querySelector('[data-upload-name]');
    if (nameBox) nameBox.textContent = filenameOf(input) || '未选择照片';
  });
})();
