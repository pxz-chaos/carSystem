(function () {
    function setStatus(form, text, ok) {
        const el = form.querySelector('.location-status');
        if (!el) return;
        el.textContent = text;
        el.className = ok ? 'location-status text-success small mb-3' : 'location-status text-warning small mb-3';
    }

    document.querySelectorAll('[data-location-form]').forEach(function (form) {
        const latInput = form.querySelector('#lat');
        const lngInput = form.querySelector('#lng');

        if (!navigator.geolocation) {
            setStatus(form, '浏览器不支持定位，地点将记录为定位失败', false);
            return;
        }

        navigator.geolocation.getCurrentPosition(
            function (pos) {
                latInput.value = pos.coords.latitude;
                lngInput.value = pos.coords.longitude;
                setStatus(form, '定位成功：' + pos.coords.latitude.toFixed(6) + ', ' + pos.coords.longitude.toFixed(6), true);
            },
            function () {
                latInput.value = '';
                lngInput.value = '';
                setStatus(form, '定位失败：请允许浏览器定位权限，或继续提交后记录为定位失败', false);
            },
            { enableHighAccuracy: true, timeout: 8000, maximumAge: 30000 }
        );
    });
})();
