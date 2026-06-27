(function () {
    function setStatus(form, text, ok) {
        const el = form.querySelector('.location-status');
        if (!el) return;
        el.textContent = text;
        el.className = ok ? 'location-status text-success small mb-3' : 'location-status text-warning small mb-3';
    }

    function resolveAddress(form, lat, lng) {
        setStatus(form, '定位成功，正在解析具体地址...', true);
        const url = '/api/reverse-geocode?lat=' + encodeURIComponent(lat) + '&lng=' + encodeURIComponent(lng);
        fetch(url, { credentials: 'same-origin' })
            .then(function (resp) { return resp.ok ? resp.json() : null; })
            .then(function (data) {
                const address = data && data.address ? String(data.address) : '';
                if (address && !/^\s*-?\d+(\.\d+)?\s*,/.test(address)) {
                    setStatus(form, '定位成功：' + address, true);
                } else {
                    setStatus(form, '定位成功：' + Number(lat).toFixed(6) + ', ' + Number(lng).toFixed(6) + '（提交后若地图接口可用会保存地址）', true);
                }
            })
            .catch(function () {
                setStatus(form, '定位成功：' + Number(lat).toFixed(6) + ', ' + Number(lng).toFixed(6) + '（地址解析失败，仍可提交）', true);
            });
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
                const lat = pos.coords.latitude;
                const lng = pos.coords.longitude;
                latInput.value = lat;
                lngInput.value = lng;
                resolveAddress(form, lat, lng);
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
