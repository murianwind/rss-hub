/* RSS Hub 화면 동작. 인라인 스크립트와 인라인 스타일은 보안 정책이 막으므로 모든 동작은 이 파일과
   data-action 속성으로 한다. 스타일은 클래스를 바꾸는 방식으로만 바꾼다. */
(function () {
  "use strict";
  var body = document.body;
  var COOKIE = "sidebar";

  function setCookie(value) {
    document.cookie = COOKIE + "=" + value + "; path=/; max-age=31536000; SameSite=Lax";
  }

  function collapsed() {
    return body.classList.contains("sidebar-collapsed");
  }

  function setCollapsed(on) {
    body.classList.toggle("sidebar-collapsed", on);
    setCookie(on ? "collapsed" : "expanded");
    var button = document.querySelector("[data-action='toggle-sidebar']");
    if (button) button.setAttribute("aria-expanded", on ? "false" : "true");
  }

  function closeDrawer() {
    body.classList.remove("drawer-open");
  }

  document.addEventListener("click", function (event) {
    var target = event.target.closest("[data-action]");
    if (target) {
      var action = target.getAttribute("data-action");
      if (action === "toggle-sidebar") setCollapsed(!collapsed());
      else if (action === "open-drawer") body.classList.add("drawer-open");
      else if (action === "close-drawer") closeDrawer();
      else if (action === "close-toast") {
        var toast = target.closest("[data-toast]");
        if (toast) toast.hidden = true;
      }
      return;
    }
    // 접힌 사이드바에서 구역 제목을 누르면 먼저 펼친다
    var head = event.target.closest(".sec > summary");
    if (head && collapsed()) setCollapsed(false);
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") closeDrawer();
  });

  // 토스트는 3초 뒤에 사라지고, 주소에서 toast 값을 지워서 새로고침해도 다시 나오지 않게 한다
  var toast = document.querySelector("[data-toast]");
  if (toast) {
    window.setTimeout(function () {
      toast.hidden = true;
    }, 3000);
    var url = new URL(window.location.href);
    if (url.searchParams.has("toast")) {
      url.searchParams.delete("toast");
      window.history.replaceState(null, "", url.pathname + url.search + url.hash);
    }
  }
})();
