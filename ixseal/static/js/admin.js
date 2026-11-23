/* IXseal 관리 화면 */
(function () {
  'use strict';

  /* ───────── 공통 ───────── */
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var clone = function (o) { return JSON.parse(JSON.stringify(o)); };
  var ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  var esc = function (s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return ESC[c]; }); };
  var SPRITE = document.body.getAttribute('data-sprite');
  var icon = function (name, cls) { return '<svg class="icon ' + (cls || '') + '" aria-hidden="true"><use href="' + SPRITE + '#' + name + '"/></svg>'; };
  var toast = function (m, k) { window.ixToast && window.ixToast(m, k); };
  var size = function (n) { return n < 1024 ? n + ' B' : n < 1048576 ? (n / 1024).toFixed(1) + ' KB' : (n / 1048576).toFixed(1) + ' MB'; };
  var ext = function (name) { var i = name.lastIndexOf('.'); return i > 0 ? name.slice(i + 1).toLowerCase() : ''; };

  var EXP = [['1h', '1시간'], ['6h', '6시간'], ['24h', '24시간'], ['3d', '3일'], ['7d', '7일']];
  var EXP_HOURS = { '1h': 1, '6h': 6, '24h': 24, '3d': 72, '7d': 168 };
  var POLICY = {
    unlimited: { opt: '기간 내 무제한', desc: '기한 안에 여러 번 열람할 수 있습니다.' },
    until_confirmed: { opt: '확인 후 폐기', desc: '고객이 [확인 완료]를 누르면 즉시 폐기됩니다.' },
    one_time: { opt: '1회 열람 후 폐기', desc: '처음 열람하는 순간 폐기됩니다. 메일 미리보기로는 소진되지 않습니다.' }
  };
  var TYPES = [['text', '텍스트'], ['secret', '비밀(가림)'], ['url', 'URL'], ['multi', '여러 줄'], ['file', '파일']];
  var BLOCKED = ('exe msi msp bat cmd com scr pif cpl ps1 psm1 psd1 vbs vbe js jse wsf wsh hta lnk jar sh bash zsh csh ksh ' +
    'bin run app dmg pkg apk dll so dylib sys drv ocx reg').split(' ');

  function boot() { var el = $('#boot'); return el ? JSON.parse(el.textContent) : {}; }

  function api(method, url, body, isForm) {
    var opts = { method: method, headers: { 'X-IXseal': '1' } };
    if (isForm) opts.body = body;
    else if (body !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
    return fetch(url, opts).then(function (r) {
      var ct = r.headers.get('content-type') || '';
      var p = ct.indexOf('json') >= 0 ? r.json() : r.text();
      return p.then(function (data) {
        if (!r.ok) throw new Error((data && data.error) || ('요청이 실패했습니다 (' + r.status + ')'));
        return data;
      });
    });
  }

  function debounce(fn, ms) {
    var t; return function () { var a = arguments; clearTimeout(t); t = setTimeout(function () { fn.apply(null, a); }, ms); };
  }

  /* ───────── 담당자 이름 (로그인 대신 브라우저에 기억) ───────── */
  var OWNER_KEY = 'ixseal.owner';
  function getOwner() { try { return localStorage.getItem(OWNER_KEY) || ''; } catch (e) { return ''; } }
  function setOwner(v) {
    try { localStorage.setItem(OWNER_KEY, v); } catch (e) { /* 저장 불가 환경 */ }
    renderOwner();
    document.dispatchEvent(new CustomEvent('ixseal-owner'));
  }
  function renderOwner() {
    var n = getOwner(), el = $('#owner-name'), btn = $('#owner-btn');
    if (el) el.textContent = n || '설정 필요';
    if (btn) btn.classList.toggle('unset', !n);
  }
  function askOwner() {
    var dlg = $('#owner-dialog'), input = $('#owner-input');
    if (!dlg || !dlg.showModal) {
      var v = (window.prompt('담당자 이름') || '').trim();
      if (v) setOwner(v.slice(0, 40));
      return Promise.resolve(v || null);
    }
    input.value = getOwner();
    return new Promise(function (resolve) {
      dlg.addEventListener('close', function onClose() {
        dlg.removeEventListener('close', onClose);
        var v = input.value.trim().slice(0, 40);
        if (dlg.returnValue === 'ok' && v) { setOwner(v); resolve(v); } else resolve(null);
      });
      dlg.showModal();
      input.focus();
    });
  }
  function ensureOwner() { var n = getOwner(); return n ? Promise.resolve(n) : askOwner(); }

  /* ───────── 미리보기 (서버가 실제 고객 화면과 같은 템플릿으로 그린다) ───────── */
  function Preview(getBody) {
    var box = $('#pv'), seg = $('#pv-seg'), view = 'reveal', ctrl = null;
    function renderSeg() {
      seg.innerHTML = [['landing', '안내'], ['reveal', '열람']].map(function (x) {
        return '<button type="button" class="' + (view === x[0] ? 'on' : '') + '" data-view="' + x[0] + '">' + x[1] + '</button>';
      }).join('');
    }
    function load() {
      if (ctrl) ctrl.abort();
      ctrl = window.AbortController ? new AbortController() : null;
      box.classList.add('loading');
      var body = getBody(view);
      fetch('/api/preview', {
        method: 'POST', headers: { 'X-IXseal': '1', 'Content-Type': 'application/json' },
        body: JSON.stringify(body), signal: ctrl ? ctrl.signal : undefined
      }).then(function (r) { if (!r.ok) throw new Error(); return r.text(); })
        .then(function (html) { box.innerHTML = html; box.classList.remove('loading'); })
        .catch(function (e) {
          if (e && e.name === 'AbortError') return;
          box.classList.remove('loading');
          box.innerHTML = '<div class="pv-error">미리보기를 만들 수 없습니다. 입력값 길이를 확인해 주세요.</div>';
        });
    }
    var refresh = debounce(load, 250);
    seg.addEventListener('click', function (e) {
      var b = e.target.closest('[data-view]'); if (!b) return;
      view = b.getAttribute('data-view'); renderSeg(); load();
    });
    box.addEventListener('click', function (e) {
      if (e.target.closest('[data-pv]')) { view = 'reveal'; renderSeg(); load(); }
      var a = e.target.closest('a[href]'); if (a && a.closest('.c-wrap')) e.preventDefault();
    });
    renderSeg();
    return { refresh: refresh, now: load };
  }

  /* ───────── 공통 위젯 ───────── */
  function segHTML(cur, act) {
    return '<div class="seg">' + EXP.map(function (x) {
      return '<button type="button" class="' + (x[0] === cur ? 'on' : '') + '" data-act="' + act + '" data-v="' + x[0] + '">' + x[1] + '</button>';
    }).join('') + '</div>';
  }
  function deadlineText(key) {
    var d = new Date(Date.now() + EXP_HOURS[key] * 3600e3);
    return (d.getMonth() + 1) + '월 ' + d.getDate() + '일 ' + String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
  }
  function genPassword() {
    var cs = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789!@#$%^&*-_=+';
    var a = new Uint32Array(20); crypto.getRandomValues(a);
    return Array.prototype.map.call(a, function (n) { return cs[n % cs.length]; }).join('');
  }
  var idx = function (s) { return s.split(',').map(Number); };
  // 안내문 입력칸은 내용 길이에 맞춰 높이를 늘린다
  function autoGrow(el) { el.style.height = 'auto'; el.style.height = (el.scrollHeight + 2) + 'px'; }
  function growAll(root) { $$('.tnotice textarea, .notice-edit textarea', root).forEach(autoGrow); }
  document.addEventListener('input', function (e) { if (e.target.matches('.tnotice textarea, .notice-edit textarea')) autoGrow(e.target); });

  /* ═════════════ 새 전달 ═════════════ */
  function initNew() {
    var B = boot(), TPLS = B.templates || [], LIM = B.limits || { maxFileMb: 20, maxFiles: 10, maxTotalMb: 50 };
    var FILES = [];          // [{file, name, size}]
    var S = null;            // 입력 상태
    var pickTarget = null;   // 파일 선택 대상 필드 경로
    var submitted = false;
    var form = $('#new-form');

    function tplById(id) { for (var i = 0; i < TPLS.length; i++) if (TPLS[i].id === id) return TPLS[i]; return null; }
    function fromTemplate(t, keep) {
      keep = keep || {};
      return {
        tplId: t ? t.id : null,
        meta: {
          customer: keep.customer || '', ticket: keep.ticket || '',
          title: keep.title || (t ? t.default_title : ''),
          expiry: t ? t.default_expiry : '24h', policy: t ? t.default_policy : 'until_confirmed'
        },
        sections: (t ? t.sections : [{ title: '계정 정보', repeat: false, unit: '', fields: [{ label: '', type: 'text', value: '', required: false }], notices: [] }])
          .map(function (s) {
            var proto = s.fields.map(function (f) { return { label: f.label, type: f.type, value: f.value || '', required: !!f.required, file_index: null, base: f.type }; });
            return { title: s.title, repeat: !!s.repeat, unit: s.unit || '항목', proto: proto, instances: [clone(proto)], notices: clone(s.notices || []) };
          })
      };
    }
    var sel = tplById(B.selected) || TPLS[0] || null;
    S = fromTemplate(sel);

    function allFields() { var out = []; S.sections.forEach(function (s) { s.instances.forEach(function (i) { out = out.concat(i); }); }); return out; }
    function missing() {
      var m = [];
      if (!S.meta.customer.trim()) m.push('고객명');
      if (!S.meta.title.trim()) m.push('제목');
      allFields().forEach(function (f) {
        if (!f.required) return;
        if (f.type === 'file' ? f.file_index == null : !String(f.value).trim()) m.push(f.label || '항목');
      });
      return m;
    }
    function dirty() {
      if (FILES.length) return true;
      return S.sections.some(function (s) {
        return s.instances.some(function (inst) {
          return inst.some(function (f, j) { return f.value && f.value !== ((s.proto[j] || {}).value || ''); });
        });
      });
    }
    function fileUses(i) {
      var out = [];
      S.sections.forEach(function (s) {
        s.instances.forEach(function (inst, ii) {
          inst.forEach(function (f) {
            if (f.type === 'file' && f.file_index === i) out.push((s.repeat ? s.unit + ' ' + (ii + 1) + ' ' : '') + (f.label || '파일'));
          });
        });
      });
      return out;
    }

    function fieldHTML(f, si, ii, fi) {
      var p = 'data-f="' + si + ',' + ii + ',' + fi + '"';
      var req = f.required ? 'req' : '', ph = f.required ? '필수 입력' : '선택 입력';
      var val;
      if (f.type === 'file') {
        var cur = f.file_index != null ? FILES[f.file_index] : null;
        var opts = FILES.map(function (x, i) { return '<option value="' + i + '">' + esc(x.name) + '</option>'; }).join('');
        val = '<div class="fpick ' + (cur ? 'has ' : '') + req + '">' +
          (cur ? '<span class="fpick-name">' + icon('i-file', 'sm') + esc(cur.name) + ' <small>' + size(cur.size) + '</small></span>'
            : '<span class="fpick-empty">' + (f.required ? '필수 · ' : '') + '파일을 선택하세요</span>') +
          (!cur && FILES.length ? '<select class="input sm" data-use-file ' + p + ' aria-label="올린 파일 사용"><option value="">올린 파일 사용…</option>' + opts + '</select>' : '') +
          '<button type="button" class="btn sm" data-act="pick" ' + p + '>' + (cur ? '변경' : '파일 선택') + '</button>' +
          (cur ? '<button type="button" class="iconbtn" aria-label="파일 빼기" data-act="unpick" ' + p + '>' + icon('i-x', 'sm') + '</button>' : '') +
          '</div>';
      } else if (f.type === 'secret') {
        val = '<div class="vwrap"><input class="input mono ' + req + '" type="' + (f.shown ? 'text' : 'password') + '" value="' + esc(f.value) + '" ' + p +
          ' data-prop="value" placeholder="' + ph + '" autocomplete="new-password" spellcheck="false">' +
          '<button type="button" class="gen" data-act="gen" ' + p + '>' + icon('i-dice', 'sm') + '생성</button></div>';
      } else if (f.type === 'multi') {
        val = '<textarea class="input mono ' + req + '" rows="2" ' + p + ' data-prop="value" placeholder="' + ph + '" spellcheck="false">' + esc(f.value) + '</textarea>';
      } else {
        val = '<input class="input mono ' + req + '" value="' + esc(f.value) + '" ' + p + ' data-prop="value" placeholder="' + ph + '" spellcheck="false">';
      }
      var mask = f.type === 'file' ? '<span></span>'
        : '<label class="toggle" title="고객 화면에서 가림"><input type="checkbox" ' + (f.type === 'secret' ? 'checked' : '') + ' ' + p + ' data-prop="secret" aria-label="가림"><span class="sw"></span></label>';
      return '<div class="frow"><input class="input" value="' + esc(f.label) + '" ' + p + ' data-prop="label" placeholder="항목 이름" aria-label="항목 이름">' +
        val + mask + '<button type="button" class="iconbtn" aria-label="항목 삭제" data-act="del-field" ' + p + '>' + icon('i-trash', 'sm') + '</button></div>';
    }

    function sectionHTML(s, si) {
      var head = '<div class="frow frow-h"><span>항목 이름</span><span>값</span><span>가림</span><span></span></div>';
      var inst = s.instances.map(function (fs, ii) {
        var body = head + fs.map(function (f, fi) { return fieldHTML(f, si, ii, fi); }).join('') +
          '<div class="add-row"><button type="button" class="btn ghost sm" data-act="add-field" data-s="' + si + '" data-i="' + ii + '">' + icon('i-plus', 'sm') + '항목</button>' +
          '<button type="button" class="btn ghost sm" data-act="add-file" data-s="' + si + '" data-i="' + ii + '">' + icon('i-key', 'sm') + '파일 항목</button></div>';
        if (!s.repeat) return '<div class="mt-14">' + body + '</div>';
        var del = s.instances.length > 1 ? '<button type="button" class="btn ghost sm" data-act="del-inst" data-s="' + si + '" data-i="' + ii + '">' + icon('i-trash', 'sm') + '이 ' + esc(s.unit) + ' 삭제</button>' : '';
        return '<div class="inst-form"><div class="inst-form-h"><span>' + esc(s.unit) + ' ' + (ii + 1) + '</span>' + del + '</div>' + body + '</div>';
      }).join('');
      var add = s.repeat ? '<button type="button" class="btn sm add-inst" data-act="add-inst" data-s="' + si + '">' + icon('i-plus', 'sm') + esc(s.unit) + ' 추가</button>' : '';
      var notes = s.notices.map(function (n, ni) {
        return '<div class="notice-edit ' + (n.tone === 'warn' ? 'warn' : 'info') + '"><label class="field-label">' + icon(n.tone === 'warn' ? 'i-alert' : 'i-info', 'sm') +
          '고객 안내문' + (n.tone === 'warn' ? ' (주의)' : '') + '</label><textarea class="input" rows="2" data-n="' + si + ',' + ni + '">' + esc(n.text) + '</textarea></div>';
      }).join('');
      return '<div class="card panel"><div class="panel-h"><h2>' + esc(s.title || '계정 정보') + '</h2>' +
        (s.repeat ? '<span class="chip">' + esc(s.unit) + ' ' + s.instances.length + '개</span>' : '') + '</div>' + inst + add + notes + '</div>';
    }

    function render() {
      var t = tplById(S.tplId);
      form.innerHTML =
        '<div class="card panel"><div class="panel-h"><h2>템플릿</h2><a class="link" href="/templates">' + icon('i-layout', 'sm') + '템플릿 관리</a></div>' +
        '<div class="tpl">' + TPLS.map(function (x) {
          return '<button type="button" class="' + (x.id === S.tplId ? 'on' : '') + '" data-act="tpl" data-id="' + esc(x.id) + '">' + esc(x.name) + '</button>';
        }).join('') + '</div><p class="desc tight">' + esc(t ? t.description : '') + '</p></div>' +

        '<div class="card panel"><h2>기본 정보</h2><p class="desc">제목과 고객명은 고객 안내 화면에 표시됩니다. 계정정보는 넣지 마세요.</p>' +
        '<div class="row2"><div><label class="field-label">고객명 <span class="req">*</span></label><input class="input" data-m="customer" maxlength="80" value="' + esc(S.meta.customer) + '" placeholder="예: 가온테크㈜"></div>' +
        '<div><label class="field-label">요청 번호</label><input class="input" data-m="ticket" maxlength="60" value="' + esc(S.meta.ticket) + '" placeholder="선택"></div></div>' +
        '<div class="row2"><div><label class="field-label">제목 <span class="req">*</span></label><input class="input" data-m="title" maxlength="120" value="' + esc(S.meta.title) + '" placeholder="예: VM 생성 완료 안내"></div>' +
        '<div><label class="field-label">담당자</label><input class="input" value="' + esc(getOwner()) + '" disabled><div class="hint">오른쪽 위 담당자 이름이 쓰입니다.</div></div></div></div>' +

        S.sections.map(sectionHTML).join('') +

        '<div class="card panel"><h2>첨부 파일</h2><p class="desc">위 항목에 넣지 않은 파일은 고객 화면의 ‘첨부 파일’에 표시됩니다.</p>' +
        '<div class="drop" id="drop" role="button" tabindex="0">' + icon('i-upload') + '<div>파일을 끌어다 놓거나 <b>선택</b>하세요</div><small>파일당 ' + LIM.maxFileMb + 'MB · 최대 ' + LIM.maxFiles + '개 · 실행 파일(.exe, .sh, .ps1 등)은 올릴 수 없습니다</small></div>' +
        (FILES.length ? '<div class="files mt">' + FILES.map(function (x, i) {
          var uses = fileUses(i);
          return '<div class="file"><div class="ext">' + esc((ext(x.name) || 'file').toUpperCase().slice(0, 4)) + '</div><div class="nm"><div>' + esc(x.name) + '</div><small>' + size(x.size) + '</small>' +
            '<div class="tags">' + (uses.length ? uses.map(function (u) { return '<span class="chip sm brand">' + esc(u) + '</span>'; }).join('') : '<span class="chip sm">첨부 파일</span>') + '</div></div>' +
            '<button type="button" class="iconbtn" aria-label="파일 제거" data-act="del-file" data-i="' + i + '">' + icon('i-x', 'sm') + '</button></div>';
        }).join('') + '</div>' : '') + '</div>' +

        '<div class="card panel"><h2>열람 설정</h2><p class="desc">템플릿 기본값이 적용되어 있습니다. 기한이 지나면 방식과 관계없이 폐기됩니다.</p>' +
        '<label class="field-label">열람 기한</label>' + segHTML(S.meta.expiry, 'exp') +
        '<label class="field-label mt-20">폐기 방식</label><div class="opts" role="radiogroup">' + Object.keys(POLICY).map(function (k) {
          var on = k === S.meta.policy;
          return '<button type="button" class="opt ' + (on ? 'on' : '') + '" role="radio" aria-checked="' + on + '" data-act="pol" data-v="' + k + '"><span class="rd"></span><span><b>' + POLICY[k].opt + '</b><small>' + POLICY[k].desc + '</small></span></button>';
        }).join('') + '</div>' +
        '<div class="submit-row"><div class="sum" id="sum"></div><button type="button" class="btn primary lg" data-act="submit">' + icon('i-lock') + '봉인하고 링크 만들기</button></div></div>';
      growAll(form);
      live();
    }

    function live() {
      var m = missing(), n = allFields().filter(function (f) { return f.type === 'file' ? f.file_index != null : String(f.value).trim(); }).length;
      $('#sum').innerHTML = '폐기 예정 <b class="num">' + deadlineText(S.meta.expiry) + '</b> · 항목 <b>' + n + '</b> · 파일 <b>' + FILES.length + '</b>' +
        (m.length ? ' · <span class="warn-t">필수 ' + m.length + '개 미입력</span>' : '');
      pv.refresh();
    }

    function apiSections() {
      return S.sections.map(function (s) {
        return {
          title: s.title, repeat: s.repeat, unit: s.unit, notices: s.notices.filter(function (n) { return n.text.trim(); }),
          instances: s.instances.map(function (inst) {
            return inst.map(function (f) {
              return { label: f.label, type: f.type, value: f.type === 'file' ? (f.file_index != null ? FILES[f.file_index].name : '') : f.value, required: !!f.required, file_index: f.type === 'file' ? f.file_index : null };
            });
          })
        };
      });
    }

    var pv = Preview(function (view) {
      return {
        view: view, mode: 'form',
        meta: { customer: S.meta.customer, title: S.meta.title, owner: getOwner() || '담당자', expiry: S.meta.expiry, policy: S.meta.policy },
        sections: apiSections(), files: FILES.map(function (x) { return { name: x.name, size: x.size }; })
      };
    });

    function addFiles(list, target) {
      var errs = [], added = -1;
      Array.prototype.forEach.call(list, function (file) {
        var e = ext(file.name);
        if (BLOCKED.indexOf(e) >= 0) { errs.push('실행 파일·스크립트(.' + e + ')는 올릴 수 없습니다'); return; }
        if (file.size === 0) { errs.push('빈 파일입니다: ' + file.name); return; }
        if (file.size > LIM.maxFileMb * 1048576) { errs.push('파일이 너무 큽니다: ' + file.name); return; }
        if (FILES.length >= LIM.maxFiles) { errs.push('파일은 ' + LIM.maxFiles + '개까지 올릴 수 있습니다'); return; }
        var total = FILES.reduce(function (a, x) { return a + x.size; }, 0) + file.size;
        if (total > LIM.maxTotalMb * 1048576) { errs.push('파일 전체 크기는 ' + LIM.maxTotalMb + 'MB까지입니다'); return; }
        FILES.push({ file: file, name: file.name, size: file.size });
        added = FILES.length - 1;
      });
      if (target && added >= 0) { var a = idx(target); S.sections[a[0]].instances[a[1]][a[2]].file_index = added; }
      if (errs.length) toast(errs[0], 'error');
      render();
    }

    function removeFile(i) {
      FILES.splice(i, 1);
      allFields().forEach(function (f) {
        if (f.type !== 'file' || f.file_index == null) return;
        if (f.file_index === i) f.file_index = null; else if (f.file_index > i) f.file_index -= 1;
      });
      render();
    }

    function showDone(r) {
      submitted = true;
      $('#new-app').innerHTML =
        '<div class="card done"><div class="done-head"><div class="ok">' + icon('i-check') + '</div><h1>봉인했습니다</h1>' +
        '<p>' + esc(S.meta.customer) + ' · ' + esc(S.meta.title) + ' · ' + esc(r.deadline) + '까지</p></div>' +
        '<div class="done-body"><div class="callout warn mb-16">' + icon('i-alert') + '<div><b>링크는 지금 한 번만 표시됩니다.</b> 잃어버리면 상세 화면에서 재발급하세요.</div></div>' +
        '<label class="field-label" for="d-link">고객용 링크</label><div class="linkbox"><input class="input" id="d-link" readonly value="' + esc(r.link) + '">' +
        '<button type="button" class="btn primary" data-copy-from="#d-link">' + icon('i-copy') + '링크 복사</button></div>' +
        '<div class="sec-title mt-24"><label for="d-mail">메일 안내문</label><button type="button" class="btn sm" data-copy-from="#d-mail">' + icon('i-mail', 'sm') + '메일 문구 복사</button></div>' +
        '<textarea class="mailbox" id="d-mail" readonly rows="14">' + esc(r.mail) + '</textarea>' +
        '<div class="done-actions"><a class="btn" href="/secrets/' + esc(r.id) + '">상세 보기</a><a class="btn" href="/secrets/new">' + icon('i-plus', 'sm') + '새 전달</a></div></div></div>';
      window.scrollTo(0, 0);
    }

    function submit(btn) {
      var m = missing();
      if (m.length) { toast('‘' + m[0] + '’을(를) 입력해 주세요', 'error'); return; }
      ensureOwner().then(function (owner) {
        if (!owner) { toast('담당자 이름을 정해 주세요', 'error'); return; }
        btn = $('[data-act="submit"]') || btn; // 이름 설정으로 폼이 다시 그려졌을 수 있다
        var body = {
          template_id: S.tplId, customer: S.meta.customer, title: S.meta.title, ticket: S.meta.ticket, owner: owner,
          expiry: S.meta.expiry, policy: S.meta.policy, sections: apiSections()
        };
        var fd = new FormData();
        fd.append('data', JSON.stringify(body));
        FILES.forEach(function (x) { fd.append('files', x.file, x.name); });
        btn.disabled = true; btn.innerHTML = icon('i-lock') + '봉인하는 중…';
        api('POST', '/api/secrets', fd, true).then(showDone).catch(function (e) {
          toast(e.message, 'error'); btn.disabled = false; btn.innerHTML = icon('i-lock') + '봉인하고 링크 만들기';
        });
      });
    }

    form.addEventListener('click', function (e) {
      var a = e.target.closest('[data-act]'); if (!a || a.disabled) return;
      var k = a.getAttribute('data-act'), s = +a.getAttribute('data-s'), i = +a.getAttribute('data-i');
      var fp = a.getAttribute('data-f'), f = fp ? idx(fp) : null;
      var field = f ? S.sections[f[0]].instances[f[1]][f[2]] : null;
      switch (k) {
        case 'tpl': {
          var id = a.getAttribute('data-id'); if (id === S.tplId) return;
          if (dirty() && !window.confirm('템플릿을 바꾸면 계정 정보와 파일 입력이 지워집니다. 바꿀까요?')) return;
          var prev = tplById(S.tplId), keepTitle = prev && S.meta.title === prev.default_title ? '' : S.meta.title;
          S = fromTemplate(tplById(id), { customer: S.meta.customer, ticket: S.meta.ticket, title: keepTitle });
          FILES = []; render(); return;
        }
        case 'add-inst': S.sections[s].instances.push(clone(S.sections[s].proto)); render(); return;
        case 'del-inst': S.sections[s].instances.splice(i, 1); render(); return;
        case 'add-field': S.sections[s].instances[i].push({ label: '', type: 'text', value: '', required: false, file_index: null, base: 'text' }); render(); return;
        case 'add-file': S.sections[s].instances[i].push({ label: '키 파일', type: 'file', value: '', required: false, file_index: null, base: 'file' }); render(); return;
        case 'del-field': S.sections[f[0]].instances[f[1]].splice(f[2], 1); render(); return;
        case 'gen': field.value = genPassword(); field.shown = true; render(); toast('새 비밀번호를 만들었습니다. 실제 계정에도 같은 값으로 설정하세요'); return;
        case 'pick': pickTarget = fp; $('#pick-input').value = ''; $('#pick-input').click(); return;
        case 'unpick': field.file_index = null; render(); return;
        case 'del-file': removeFile(i); return;
        case 'exp': S.meta.expiry = a.getAttribute('data-v'); render(); return;
        case 'pol': S.meta.policy = a.getAttribute('data-v'); render(); return;
        case 'submit': submit(a); return;
      }
    });
    form.addEventListener('input', function (e) {
      var el = e.target;
      if (el.hasAttribute('data-m')) { S.meta[el.getAttribute('data-m')] = el.value; live(); return; }
      if (el.hasAttribute('data-f') && el.getAttribute('data-prop') !== 'secret' && !el.hasAttribute('data-use-file')) {
        var f = idx(el.getAttribute('data-f')); S.sections[f[0]].instances[f[1]][f[2]][el.getAttribute('data-prop')] = el.value; live(); return;
      }
      if (el.hasAttribute('data-n')) { var n = idx(el.getAttribute('data-n')); S.sections[n[0]].notices[n[1]].text = el.value; live(); }
    });
    form.addEventListener('change', function (e) {
      var el = e.target, fp = el.getAttribute('data-f'); if (!fp) return;
      var f = idx(fp), field = S.sections[f[0]].instances[f[1]][f[2]];
      if (el.getAttribute('data-prop') === 'secret') { field.type = el.checked ? 'secret' : (field.base === 'secret' ? 'text' : field.base || 'text'); render(); return; }
      if (el.hasAttribute('data-use-file') && el.value !== '') { field.file_index = +el.value; render(); }
    });

    $('#pick-input').addEventListener('change', function (e) { if (e.target.files.length) addFiles(e.target.files, pickTarget); pickTarget = null; });
    $('#attach-input').addEventListener('change', function (e) { if (e.target.files.length) addFiles(e.target.files, null); });
    form.addEventListener('click', function (e) { if (e.target.closest('#drop')) $('#attach-input').click(); });
    form.addEventListener('keydown', function (e) { if ((e.key === 'Enter' || e.key === ' ') && e.target.id === 'drop') { e.preventDefault(); $('#attach-input').click(); } });
    form.addEventListener('dragover', function (e) { var d = e.target.closest('#drop'); if (d) { e.preventDefault(); d.classList.add('over'); } });
    form.addEventListener('dragleave', function (e) { var d = e.target.closest('#drop'); if (d) d.classList.remove('over'); });
    form.addEventListener('drop', function (e) { var d = e.target.closest('#drop'); if (d) { e.preventDefault(); addFiles(e.dataTransfer.files, null); } });
    window.addEventListener('beforeunload', function (e) { if (!submitted && dirty()) { e.preventDefault(); e.returnValue = ''; } });
    document.addEventListener('ixseal-owner', function () { if (!submitted) render(); });

    render();
  }

  /* ═════════════ 템플릿 편집 ═════════════ */
  function initTemplateEdit() {
    var B = boot(), orig = B.template;
    var T = orig ? clone(orig) : {
      name: '', description: '', default_title: '', default_expiry: '24h', default_policy: 'until_confirmed',
      sections: [{ title: '', repeat: false, unit: '', fields: [{ label: '', type: 'text', value: '', required: true }], notices: [] }]
    };
    var form = $('#tpl-form');
    if (orig) $('#tpl-archive').hidden = false;

    function ud(k, si, i, n) {
      return '<button type="button" class="iconbtn" aria-label="위로" data-act="' + k + '-up" data-s="' + si + '" data-i="' + i + '"' + (i === 0 ? ' disabled' : '') + '>' + icon('i-up', 'sm') + '</button>' +
        '<button type="button" class="iconbtn" aria-label="아래로" data-act="' + k + '-down" data-s="' + si + '" data-i="' + i + '"' + (i === n - 1 ? ' disabled' : '') + '>' + icon('i-down', 'sm') + '</button>';
    }
    function render() {
      $('#tpl-title').textContent = orig ? '템플릿 편집 · ' + (T.name || '이름 없음') : '새 템플릿';
      form.innerHTML =
        '<div class="card panel"><h2>템플릿 정보</h2><p class="desc">새 전달 화면에서 이 템플릿을 고르면 아래 값이 기본으로 채워집니다.</p>' +
        '<div class="row2"><div><label class="field-label">템플릿 이름 <span class="req">*</span></label><input class="input" data-t="name" maxlength="60" value="' + esc(T.name) + '" placeholder="예: 신규 계정 + VM"></div>' +
        '<div><label class="field-label">기본 제목</label><input class="input" data-t="default_title" maxlength="120" value="' + esc(T.default_title) + '" placeholder="고객 화면 제목"></div></div>' +
        '<div class="field mt-14"><label class="field-label">설명</label><input class="input" data-t="description" maxlength="200" value="' + esc(T.description) + '" placeholder="언제 쓰는 템플릿인지"></div>' +
        '<div class="row2"><div><label class="field-label">기본 열람 기한</label>' + segHTML(T.default_expiry, 't-exp') + '</div>' +
        '<div><label class="field-label">기본 폐기 방식</label><select class="input" data-t="default_policy">' + Object.keys(POLICY).map(function (k) {
          return '<option value="' + k + '"' + (k === T.default_policy ? ' selected' : '') + '>' + POLICY[k].opt + '</option>';
        }).join('') + '</select></div></div></div>' +

        T.sections.map(function (s, si) {
          return '<div class="card panel"><div class="sec-edit-h"><span class="sec-no">' + (si + 1) + '</span>' +
            '<input class="input title-in" data-ts="' + si + '" data-prop="title" maxlength="60" value="' + esc(s.title) + '" placeholder="섹션 제목 (예: VM 접속 정보)" aria-label="섹션 제목">' +
            '<label class="toggle" title="같은 묶음을 여러 개 넣을 수 있게 합니다"><input type="checkbox" data-ts="' + si + '" data-prop="repeat"' + (s.repeat ? ' checked' : '') + '><span class="sw"></span>여러 개</label>' +
            (s.repeat ? '<input class="input unit-in" data-ts="' + si + '" data-prop="unit" maxlength="20" value="' + esc(s.unit) + '" placeholder="단위 (예: VM)" aria-label="단위">' : '') +
            ud('sec', si, si, T.sections.length) +
            '<button type="button" class="iconbtn" aria-label="섹션 삭제" data-act="del-sec" data-s="' + si + '">' + icon('i-trash', 'sm') + '</button></div>' +
            '<div class="trow trow-h"><span>항목 이름</span><span>유형</span><span>기본값 <small>· 비우면 등록 시 입력</small></span><span>필수</span><span></span><span></span><span></span></div>' +
            s.fields.map(function (f, fi) {
              var p = 'data-tf="' + si + ',' + fi + '"', noDefault = f.type === 'secret' || f.type === 'file';
              return '<div class="trow"><input class="input" ' + p + ' data-prop="label" maxlength="60" value="' + esc(f.label) + '" placeholder="항목 이름" aria-label="항목 이름">' +
                '<select class="input" ' + p + ' data-prop="type" aria-label="유형">' + TYPES.map(function (x) { return '<option value="' + x[0] + '"' + (x[0] === f.type ? ' selected' : '') + '>' + x[1] + '</option>'; }).join('') + '</select>' +
                '<input class="input mono" ' + p + ' data-prop="value" maxlength="2000" value="' + esc(noDefault ? '' : f.value) + '"' + (noDefault ? ' disabled placeholder="' + (f.type === 'file' ? '등록할 때 파일 선택' : '비밀 값은 기본값 없음') + '"' : ' placeholder="(없음)"') + ' aria-label="기본값">' +
                '<label class="toggle" title="필수 입력"><input type="checkbox" ' + p + ' data-prop="required"' + (f.required ? ' checked' : '') + ' aria-label="필수"><span class="sw"></span></label>' +
                ud('f', si, fi, s.fields.length) +
                '<button type="button" class="iconbtn" aria-label="항목 삭제" data-act="del-f" data-s="' + si + '" data-i="' + fi + '">' + icon('i-trash', 'sm') + '</button></div>';
            }).join('') +
            (s.notices.length ? '<div class="tnotice-h">고객 안내문 <small>· URL과 메일 주소는 자동으로 링크가 됩니다</small></div>' : '') +
            s.notices.map(function (n, ni) {
              var p = 'data-tn="' + si + ',' + ni + '"';
              return '<div class="tnotice"><select class="input" ' + p + ' data-prop="tone" aria-label="안내 종류"><option value="info"' + (n.tone !== 'warn' ? ' selected' : '') + '>안내</option><option value="warn"' + (n.tone === 'warn' ? ' selected' : '') + '>주의</option></select>' +
                '<textarea class="input" rows="2" ' + p + ' data-prop="text" maxlength="1000" placeholder="고객에게 보여 줄 안내">' + esc(n.text) + '</textarea>' +
                '<button type="button" class="iconbtn" aria-label="안내문 삭제" data-act="del-n" data-s="' + si + '" data-i="' + ni + '">' + icon('i-trash', 'sm') + '</button></div>';
            }).join('') +
            '<div class="sec-actions"><button type="button" class="btn ghost sm" data-act="add-f" data-s="' + si + '">' + icon('i-plus', 'sm') + '항목</button>' +
            '<button type="button" class="btn ghost sm" data-act="add-n" data-s="' + si + '">' + icon('i-plus', 'sm') + '안내문</button></div></div>';
        }).join('') +
        '<button type="button" class="btn dashed block" data-act="add-sec">' + icon('i-plus') + '섹션 추가</button>';
      growAll(form);
      pv.refresh();
    }

    var pv = Preview(function (view) {
      return {
        view: view, mode: 'tpl',
        meta: { customer: '고객사명', title: T.default_title || '(전달 제목)', owner: getOwner() || '담당자', expiry: T.default_expiry, policy: T.default_policy },
        sections: T.sections.map(function (s) {
          return {
            title: s.title, repeat: s.repeat, unit: s.unit, notices: s.notices,
            instances: [s.fields.map(function (f) { return { label: f.label, type: f.type, value: f.type === 'secret' || f.type === 'file' ? '' : f.value, required: f.required }; })]
          };
        }),
        files: []
      };
    });
    document.addEventListener('ixseal-owner', function () { pv.refresh(); });

    function swap(a, i, j) { if (j < 0 || j >= a.length) return; var t = a[i]; a[i] = a[j]; a[j] = t; }
    var newField = function () { return { label: '', type: 'text', value: '', required: true }; };

    function save(btn) {
      if (!T.name.trim()) { toast('템플릿 이름을 입력해 주세요', 'error'); var n = $('[data-t="name"]'); n && n.focus(); return; }
      ensureOwner().then(function (owner) {
        if (!owner) return;
        var body = {
          name: T.name, description: T.description, default_title: T.default_title, default_expiry: T.default_expiry, default_policy: T.default_policy,
          updated_by: owner,
          sections: T.sections.map(function (s) {
            return {
              title: s.title, repeat: s.repeat, unit: s.repeat ? (s.unit || '항목') : '',
              fields: s.fields.map(function (f) { return { label: f.label, type: f.type, value: f.type === 'secret' || f.type === 'file' ? '' : f.value, required: !!f.required }; }),
              notices: s.notices.filter(function (n) { return n.text.trim(); })
            };
          })
        };
        btn.disabled = true;
        (orig ? api('PUT', '/api/templates/' + orig.id, body) : api('POST', '/api/templates', body))
          .then(function () { location.href = '/templates'; })
          .catch(function (e) { toast(e.message, 'error'); btn.disabled = false; });
      });
    }

    document.addEventListener('click', function (e) {
      var a = e.target.closest('[data-act]'); if (!a || a.disabled) return;
      var k = a.getAttribute('data-act'), si = +a.getAttribute('data-s'), i = +a.getAttribute('data-i');
      switch (k) {
        case 't-save': save(a); return;
        case 't-archive':
          if (!window.confirm('이 템플릿을 삭제할까요? 이미 보낸 전달에는 영향이 없습니다.')) return;
          ensureOwner().then(function (owner) {
            if (!owner) return;
            api('POST', '/api/templates/' + orig.id + '/archive', { owner: owner }).then(function () { location.href = '/templates'; })
              .catch(function (er) { toast(er.message, 'error'); });
          });
          return;
        case 't-exp': T.default_expiry = a.getAttribute('data-v'); render(); return;
        case 'add-sec': T.sections.push({ title: '', repeat: false, unit: '', fields: [newField()], notices: [] }); render(); return;
        case 'del-sec':
          if (T.sections.length < 2) { toast('섹션은 하나 이상 있어야 합니다', 'error'); return; }
          if (window.confirm('이 섹션을 삭제할까요?')) { T.sections.splice(si, 1); render(); }
          return;
        case 'sec-up': swap(T.sections, i, i - 1); render(); return;
        case 'sec-down': swap(T.sections, i, i + 1); render(); return;
        case 'add-f': T.sections[si].fields.push(newField()); render(); return;
        case 'del-f': T.sections[si].fields.splice(i, 1); render(); return;
        case 'f-up': swap(T.sections[si].fields, i, i - 1); render(); return;
        case 'f-down': swap(T.sections[si].fields, i, i + 1); render(); return;
        case 'add-n': T.sections[si].notices.push({ tone: 'info', text: '' }); render(); return;
        case 'del-n': T.sections[si].notices.splice(i, 1); render(); return;
      }
    });
    form.addEventListener('input', function (e) {
      var el = e.target, prop = el.getAttribute('data-prop');
      if (el.hasAttribute('data-t') && el.tagName !== 'SELECT') { T[el.getAttribute('data-t')] = el.value; if (el.getAttribute('data-t') === 'name') $('#tpl-title').textContent = orig ? '템플릿 편집 · ' + (el.value || '이름 없음') : '새 템플릿'; pv.refresh(); return; }
      if (el.hasAttribute('data-ts') && el.type !== 'checkbox') { T.sections[+el.getAttribute('data-ts')][prop] = el.value; pv.refresh(); return; }
      if (el.hasAttribute('data-tf') && el.type !== 'checkbox' && el.tagName !== 'SELECT') { var f = idx(el.getAttribute('data-tf')); T.sections[f[0]].fields[f[1]][prop] = el.value; pv.refresh(); return; }
      if (el.hasAttribute('data-tn') && el.tagName === 'TEXTAREA') { var n = idx(el.getAttribute('data-tn')); T.sections[n[0]].notices[n[1]].text = el.value; pv.refresh(); }
    });
    form.addEventListener('change', function (e) {
      var el = e.target, prop = el.getAttribute('data-prop');
      if (el.getAttribute('data-t') === 'default_policy') { T.default_policy = el.value; pv.refresh(); return; }
      if (el.hasAttribute('data-ts') && el.type === 'checkbox') { var s = T.sections[+el.getAttribute('data-ts')]; s.repeat = el.checked; if (s.repeat && !s.unit) s.unit = '항목'; render(); return; }
      if (el.hasAttribute('data-tf') && el.type === 'checkbox') { var f = idx(el.getAttribute('data-tf')); T.sections[f[0]].fields[f[1]].required = el.checked; pv.refresh(); return; }
      if (el.hasAttribute('data-tf') && el.tagName === 'SELECT') { var g = idx(el.getAttribute('data-tf')), fld = T.sections[g[0]].fields[g[1]]; fld.type = el.value; if (fld.type === 'secret' || fld.type === 'file') fld.value = ''; render(); return; }
      if (el.hasAttribute('data-tn') && el.tagName === 'SELECT') { var n = idx(el.getAttribute('data-tn')); T.sections[n[0]].notices[n[1]].tone = el.value; pv.refresh(); }
    });
    render();
  }

  /* ═════════════ 목록 · 상세 · 템플릿 목록 ═════════════ */
  function initList() {
    $$('.bar i[data-pct]').forEach(function (i) { i.style.width = Math.max(0, Math.min(100, +i.getAttribute('data-pct'))) + '%'; });
    document.addEventListener('click', function (e) {
      var tr = e.target.closest('tr[data-href]');
      if (tr && !e.target.closest('a, button')) location.href = tr.getAttribute('data-href');
    });
  }

  function initDetail() {
    var id = $('[data-secret-id]').getAttribute('data-secret-id');
    document.addEventListener('click', function (e) {
      var a = e.target.closest('[data-act]'); if (!a) return;
      var k = a.getAttribute('data-act');
      if (k === 'revoke') {
        if (!window.confirm('회수하면 고객이 더 이상 열람할 수 없고 내용은 즉시 삭제됩니다. 회수할까요?')) return;
        ensureOwner().then(function (owner) {
          if (!owner) return;
          api('POST', '/api/secrets/' + id + '/revoke', { owner: owner }).then(function () { location.reload(); }).catch(function (er) { toast(er.message, 'error'); });
        });
      } else if (k === 'reissue') {
        if (!window.confirm('새 링크를 만들까요? 기존 링크는 즉시 열리지 않게 됩니다.')) return;
        ensureOwner().then(function (owner) {
          if (!owner) return;
          api('POST', '/api/secrets/' + id + '/reissue', { owner: owner }).then(function (r) {
            $('#ld-link').value = r.link; $('#ld-mail').value = r.mail; $('#link-dialog').showModal();
          }).catch(function (er) { toast(er.message, 'error'); });
        });
      }
    });
    document.addEventListener('click', function (e) { if (e.target.closest('[data-reload]')) location.reload(); });
  }

  function initTemplates() {
    document.addEventListener('click', function (e) {
      var a = e.target.closest('[data-act="dup"]'); if (!a) return;
      ensureOwner().then(function (owner) {
        if (!owner) return;
        api('POST', '/api/templates/' + a.getAttribute('data-id') + '/duplicate', { owner: owner })
          .then(function (r) { location.href = '/templates/' + r.id + '/edit'; })
          .catch(function (er) { toast(er.message, 'error'); });
      });
    });
  }

  /* ───────── 시작 ───────── */
  document.addEventListener('click', function (e) {
    var c = e.target.closest('[data-copy-from]'); if (!c) return;
    var src = $(c.getAttribute('data-copy-from'));
    window.ixCopy(src.value).then(function () { toast('복사했습니다'); }, function () { src.select(); toast('복사하지 못했습니다. 직접 복사해 주세요', 'error'); });
  });
  var ob = $('#owner-btn'); if (ob) ob.addEventListener('click', askOwner);
  // 이름 입력칸에서 Enter = 저장 (기본 동작은 첫 버튼인 '취소'로 제출된다)
  var oi = $('#owner-input');
  if (oi) oi.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); $('#owner-dialog').close('ok'); } });
  renderOwner();

  var page = document.body.getAttribute('data-page');
  if (page === 'new') initNew();
  else if (page === 'template-edit') initTemplateEdit();
  else if (page === 'list') initList();
  else if (page === 'detail') initDetail();
  else if (page === 'templates') initTemplates();
  if (!getOwner() && (page === 'new' || page === 'template-edit')) askOwner();
})();
