(function () {
    'use strict';

    // Zotonic-style: elements with class="do_anchor" carry their target
    // in the href attribute (even on <button>). On click, smooth-scroll
    // to that element. Drives the round arrow button on theme pages and
    // the home-page 'jump to stories' arrow.
    function onAnchorClick(e) {
        var target = this.getAttribute('href') || '';
        if (target.charAt(0) !== '#' || target === '#') return;
        var tgt;
        try {
            tgt = document.querySelector(target);
        } catch (_) {
            return;
        }
        if (!tgt) return;
        e.preventDefault();
        tgt.scrollIntoView({behavior: 'smooth', block: 'start'});
    }

    function bind() {
        var els = document.querySelectorAll('.do_anchor');
        for (var i = 0; i < els.length; i++) {
            els[i].addEventListener('click', onAnchorClick);
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bind);
    } else {
        bind();
    }
})();
