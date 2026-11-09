// PiCsys デジタル四日市：ページの小さな動き

(function () {
  // スマホ用メニューの開け閉め
  var menuBtn = document.querySelector('.menu-btn');
  var nav = document.getElementById('global-nav');

  if (menuBtn && nav) {
    var setOpen = function (open) {
      menuBtn.setAttribute('aria-expanded', String(open));
      nav.classList.toggle('is-open', open);
    };

    menuBtn.addEventListener('click', function () {
      setOpen(menuBtn.getAttribute('aria-expanded') !== 'true');
    });

    // メニュー内のリンクを押したら閉じる
    nav.addEventListener('click', function (e) {
      if (e.target.closest('a')) setOpen(false);
    });

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') setOpen(false);
    });
  }

  // 料金表のタブ（スマホ／パソコン）
  var tabs = Array.prototype.slice.call(document.querySelectorAll('.tab'));

  var selectTab = function (tab) {
    tabs.forEach(function (t) {
      var selected = t === tab;
      t.setAttribute('aria-selected', String(selected));
      t.tabIndex = selected ? 0 : -1;
      var panel = document.getElementById(t.getAttribute('aria-controls'));
      if (panel) panel.hidden = !selected;
    });
  };

  tabs.forEach(function (tab, i) {
    tab.addEventListener('click', function () { selectTab(tab); });
    tab.addEventListener('keydown', function (e) {
      if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
      var next = tabs[(i + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
      selectTab(next);
      next.focus();
    });
  });

  // フッターの年
  var year = document.getElementById('year');
  if (year) year.textContent = new Date().getFullYear();
})();
