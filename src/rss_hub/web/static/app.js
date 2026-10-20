/* RSS Hub 화면 동작. 인라인 스크립트와 인라인 스타일은 보안 정책이 막으므로 모든 동작은 이 파일과
   data-* 속성으로 한다. 스타일은 클래스를 바꾸는 방식으로만 바꾼다. 서버가 준 HTML 조각은
   DOMParser로 해석해서 끼워 넣는다(우리 서버가 이스케이프해서 그린 것만 받는다). */
(function () {
  "use strict";
  var body = document.body;
  var COOKIE = "sidebar";
  var slot = document.getElementById("panel-slot");

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

  // ---------- 토스트 ----------
  function showToast(message) {
    var old = document.querySelector("[data-toast]");
    if (old) old.remove();
    var box = document.createElement("div");
    box.className = "toast";
    box.setAttribute("role", "status");
    box.setAttribute("data-toast", "");
    var text = document.createElement("span");
    text.textContent = message;
    var close = document.createElement("button");
    close.type = "button";
    close.className = "icon-btn";
    close.setAttribute("data-action", "close-toast");
    close.setAttribute("aria-label", "닫기");
    close.textContent = "×";
    box.appendChild(text);
    box.appendChild(close);
    document.querySelector(".main").appendChild(box);
    window.setTimeout(function () {
      box.hidden = true;
    }, 3000);
  }

  // ---------- 슬라이드 패널 ----------
  function closePanel() {
    if (!slot || slot.hidden) return;
    slot.classList.remove("open");
    window.setTimeout(function () {
      slot.replaceChildren();
      slot.hidden = true;
    }, 260);
  }

  function openPanel(url) {
    fetch(url, { headers: { "X-Panel": "1" }, credentials: "same-origin" })
      .then(function (response) {
        if (!response.ok) throw new Error(String(response.status));
        return response.text();
      })
      .then(function (text) {
        var doc = new DOMParser().parseFromString(text, "text/html");
        slot.replaceChildren.apply(slot, Array.from(doc.body.childNodes));
        slot.hidden = false;
        window.requestAnimationFrame(function () {
          slot.classList.add("open");
        });
        var first = slot.querySelector("input:not([type=hidden]), select, textarea");
        if (first) first.focus();
      })
      .catch(function () {
        window.location.href = url; // 받지 못하면 전체 화면으로 연다
      });
  }

  // ---------- 클릭 ----------
  document.addEventListener("click", function (event) {
    var opener = event.target.closest("a[data-panel]");
    if (opener && slot && event.button === 0 && !event.ctrlKey && !event.metaKey && !event.shiftKey) {
      event.preventDefault();
      closeDrawer();
      openPanel(opener.href);
      return;
    }
    var target = event.target.closest("[data-action]");
    if (target) {
      var action = target.getAttribute("data-action");
      if (action === "toggle-sidebar") setCollapsed(!collapsed());
      else if (action === "open-drawer") body.classList.add("drawer-open");
      else if (action === "close-drawer") closeDrawer();
      else if (action === "close-panel") {
        if (slot && slot.contains(target)) {
          event.preventDefault();
          closePanel();
        }
      } else if (action === "close-toast") {
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
    if (event.key === "Escape") {
      closeDrawer();
      closePanel();
    }
  });

  // ---------- 드래그: 순서 바꾸기와 피드를 카테고리로 옮기기 ----------
  var dragged = null;
  var reordered = false;

  function post(url, data) {
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams(data).toString(),
    }).then(function (response) {
      return response.text().then(function (text) {
        return { ok: response.ok, text: text };
      });
    });
  }

  function clearOver() {
    document.querySelectorAll(".drop-over").forEach(function (el) {
      el.classList.remove("drop-over");
    });
  }

  document.addEventListener("dragstart", function (event) {
    var row = event.target.closest ? event.target.closest("[data-drag-kind]") : null;
    if (!row) return;
    dragged = row;
    reordered = false;
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData(
      "text/plain",
      row.getAttribute("data-drag-kind") + ":" + row.getAttribute("data-drag-id")
    );
    window.setTimeout(function () {
      row.classList.add("dragging");
    }, 0);
  });

  document.addEventListener("dragover", function (event) {
    if (!dragged) return;
    var kind = dragged.getAttribute("data-drag-kind");
    var list = event.target.closest("[data-reorder]");
    if (list && list.getAttribute("data-reorder") === kind && list.contains(dragged)) {
      event.preventDefault();
      var rows = Array.prototype.filter.call(list.children, function (child) {
        return child !== dragged && child.hasAttribute("data-drag-kind");
      });
      var next = rows.find(function (child) {
        var box = child.getBoundingClientRect();
        return event.clientY < box.top + box.height / 2;
      });
      if (next) {
        if (dragged.nextElementSibling !== next) {
          list.insertBefore(dragged, next);
          reordered = true;
        }
      } else if (list.lastElementChild !== dragged) {
        list.appendChild(dragged);
        reordered = true;
      }
      return;
    }
    clearOver();
    if (kind === "feed") {
      var target = event.target.closest("[data-drop-category]");
      if (target) {
        event.preventDefault();
        target.classList.add("drop-over");
      }
    }
  });

  document.addEventListener("drop", function (event) {
    if (!dragged || dragged.getAttribute("data-drag-kind") !== "feed") return;
    var target = event.target.closest("[data-drop-category]");
    if (!target) return;
    event.preventDefault();
    post("/ui/move-feed", {
      feed_id: dragged.getAttribute("data-drag-id"),
      category_id: target.getAttribute("data-drop-category"),
    }).then(function (result) {
      if (result.ok) {
        var url = new URL(window.location.href);
        url.searchParams.set("toast", "moved");
        window.location.href = url.toString();
      } else {
        showToast(result.text);
      }
    });
  });

  document.addEventListener("dragend", function () {
    var row = dragged;
    dragged = null;
    clearOver();
    if (!row) return;
    row.classList.remove("dragging");
    if (!reordered) return;
    reordered = false;
    var list = row.closest("[data-reorder]");
    var ids = Array.prototype.map.call(list.querySelectorAll(":scope > [data-drag-kind]"), function (c) {
      return c.getAttribute("data-drag-id");
    });
    post("/ui/reorder", { kind: row.getAttribute("data-drag-kind"), ids: ids.join(",") }).then(function (result) {
      if (!result.ok) showToast(result.text);
    });
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
