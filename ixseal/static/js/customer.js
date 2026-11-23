/* IXseal 고객 화면: 값 보기·복사, 남은 시간, 폐기 확인. 관리 화면 미리보기에서도 같은 동작을 쓴다. */
(function () {
  'use strict';

  var toastTimer;
  function toast(msg, kind) {
    var el = document.getElementById('toast');
    if (!el) return;
    el.querySelector('span').textContent = msg;
    el.classList.toggle('error', kind === 'error');
    var use = el.querySelector('use');
    if (use) use.setAttribute('href', use.getAttribute('href').replace(/#.*$/, kind === 'error' ? '#i-alert' : '#i-check'));
    el.classList.add('on');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.classList.remove('on'); }, 2400);
  }
  window.ixToast = toast;

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
    return new Promise(function (resolve, reject) {
      var ta = document.createElement('textarea');
      ta.value = text; ta.setAttribute('readonly', '');
      ta.className = 'sr-only';
      document.body.appendChild(ta); ta.select();
      try { document.execCommand('copy') ? resolve() : reject(); } catch (e) { reject(e); }
      document.body.removeChild(ta);
    });
  }
  window.ixCopy = copyText;

  function swapIcon(btn, name) {
    var use = btn.querySelector('use');
    if (use) use.setAttribute('href', use.getAttribute('href').replace(/#.*$/, '#' + name));
  }

  document.addEventListener('click', function (e) {
    var r = e.target.closest('[data-reveal]');
    if (r) {
      var v = r.closest('.v');
      var shown = v.classList.toggle('shown');
      swapIcon(r, shown ? 'i-eyeoff' : 'i-eye');
      r.setAttribute('aria-label', (shown ? '가리기' : '보기'));
      return;
    }
    var c = e.target.closest('[data-copy]');
    if (c) {
      var box = c.closest('.v');
      var real = box && box.querySelector('.real');
      var label = (c.closest('.item') || document).querySelector('.k');
      var name = label ? label.textContent.trim() : '값';
      if (!real) return;
      copyText(real.textContent).then(
        function () { toast(name + ' 복사했습니다' + (box.classList.contains('secret') ? ' · 사용 후 클립보드를 비워 주세요' : '')); },
        function () { toast('복사하지 못했습니다. 직접 선택해 복사해 주세요', 'error'); }
      );
    }
  });

  document.addEventListener('submit', function (e) {
    var f = e.target.closest('form[data-confirm]');
    if (f && !window.confirm(f.getAttribute('data-confirm'))) e.preventDefault();
  });

  // 남은 시간 (48시간 미만은 시간 단위)
  function remaining(iso) {
    var secs = Math.floor((new Date(iso).getTime() - Date.now()) / 1000);
    if (secs <= 0) return '만료됨';
    var mins = Math.ceil(secs / 60);
    var days = mins >= 2880 ? Math.floor(mins / 1440) : 0;
    var hours = Math.floor((mins - days * 1440) / 60);
    var m = mins % 60;
    var out = [];
    if (days) out.push(days + '일');
    if (hours) out.push(hours + '시간');
    if (m && !days) out.push(m + '분');
    return out.join(' ') || '1분 미만';
  }
  window.ixRemaining = remaining;

  function tick() {
    document.querySelectorAll('[data-expires]').forEach(function (el) {
      var t = remaining(el.getAttribute('data-expires'));
      el.textContent = el.hasAttribute('data-short') ? t : '· ' + t + (t === '만료됨' ? '' : ' 남음');
    });
    document.querySelectorAll('[data-countdown]').forEach(function (el) {
      var left = parseInt(el.getAttribute('data-countdown'), 10) - 1;
      if (left < 0) left = 0;
      el.setAttribute('data-countdown', String(left));
      el.textContent = Math.floor(left / 60) + ':' + String(left % 60).padStart(2, '0');
    });
  }
  setInterval(tick, 1000);
})();
