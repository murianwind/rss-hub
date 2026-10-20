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
    var refresher = event.target.closest("[data-refresh]");
    if (refresher) {
      event.preventDefault();
      refreshFeed(refresher);
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

  // ---------- 사이드바 상태(개수와 피드 상태 점)를 화면을 다시 불러오지 않고 고친다 ----------
  var STATE_LABEL = { ok: "정상", error: "오류", never: "아직 수집 전" };

  function setBadge(el, unread, total) {
    el.classList.toggle("unread", unread > 0);
    el.textContent = unread > 0 ? String(unread) : total > 0 ? String(total) : "";
    el.hidden = !(unread > 0 || total > 0);
    el.title = unread > 0 ? "안 읽은 글 " + unread + "개" : "글 " + total + "개";
  }

  function setCount(key, unread, total) {
    document.querySelectorAll('[data-count="' + key + '"]').forEach(function (el) {
      setBadge(el, unread, total);
    });
  }

  function applyState(state) {
    Object.keys(state.feeds).forEach(function (id) {
      var feed = state.feeds[id];
      setCount("feed:" + id, feed.unread, feed.total);
      document.querySelectorAll('[data-state="' + id + '"]').forEach(function (dot) {
        dot.className = "state-dot " + feed.state;
        dot.setAttribute("aria-label", STATE_LABEL[feed.state]);
        dot.title = feed.state === "error" ? "오류: " + feed.error : STATE_LABEL[feed.state];
      });
    });
    Object.keys(state.categories).forEach(function (id) {
      setCount("category:" + id, state.categories[id].unread, state.categories[id].total);
    });
    Object.keys(state.topics).forEach(function (id) {
      setCount("topic:" + id, state.topics[id].unread, state.topics[id].total);
    });
    setCount("all", state.all_unread, 0);
    setCount("bookmarks", 0, state.bookmarks);
  }

  function refreshFeed(button) {
    if (button.disabled) return;
    button.disabled = true;
    button.classList.add("refreshing");
    post("/feeds/" + button.getAttribute("data-refresh") + "/refresh", {})
      .then(function (result) {
        var data = null;
        try {
          data = JSON.parse(result.text);
        } catch (error) {
          data = null;
        }
        if (data && data.state) applyState(data.state);
        if (!data) showToast("다시 읽지 못했습니다.");
        else if (!data.ok) showToast("읽지 못했습니다: " + data.error);
        else if (data.added > 0) showToast("새 글 " + data.added + "개를 가져왔습니다.");
        else showToast("다시 읽었습니다. 새 글은 없습니다.");
      })
      .catch(function () {
        showToast("다시 읽지 못했습니다.");
      })
      .then(function () {
        button.disabled = false;
        button.classList.remove("refreshing");
      });
  }

  // ---------- 읽음: 카드의 읽음 버튼과 스크롤 자동 읽음 ----------
  function setCardRead(card, read) {
    card.classList.toggle("unread", !read);
    var title = card.querySelector("h2 a");
    var dot = title.querySelector(".dot");
    if (read && dot) dot.remove();
    if (!read && !dot) {
      dot = document.createElement("span");
      dot.className = "dot";
      dot.title = "안 읽은 글";
      title.insertBefore(dot, title.firstChild);
    }
    var form = card.querySelector("form[data-read-toggle]");
    if (form) {
      form.elements.state.value = read ? "unread" : "read";
      form.querySelector("button").textContent = read ? "안 읽음으로 표시" : "읽음으로 표시";
    }
  }

  function readStateOf(result) {
    try {
      return JSON.parse(result.text);
    } catch (error) {
      return null;
    }
  }

  document.addEventListener("submit", function (event) {
    var form = event.target.closest ? event.target.closest("form[data-read-toggle]") : null;
    if (!form) return;
    event.preventDefault();
    var card = form.closest("article.card");
    post("/ui/read-state", {
      id: form.getAttribute("data-read-toggle"),
      state: form.elements.state.value,
    })
      .then(function (result) {
        var data = readStateOf(result);
        if (!data || !data.ok) throw new Error("rejected");
        setCardRead(card, data.read);
        // 사용자가 직접 안 읽음으로 바꾼 글은 스크롤해도 자동으로 읽음 처리하지 않는다
        if (data.read) card.removeAttribute("data-keep");
        else card.setAttribute("data-keep", "1");
        applyState(data.state);
      })
      .catch(function () {
        showToast("읽음 상태를 바꾸지 못했습니다.");
      });
  });

  var cardList = document.querySelector(".list");
  var scrollBox = document.querySelector(".main .scroll");
  if (cardList && scrollBox && document.body.getAttribute("data-auto-read") === "on") {
    var waiting = new Set();
    var flushTimer = null;
    var queued = false;

    var flush = function () {
      var ids = Array.from(waiting);
      waiting.clear();
      if (!ids.length) return;
      post("/ui/auto-read", { ids: ids.join(",") }).then(function (result) {
        var data = readStateOf(result);
        if (data && data.state) applyState(data.state);
      });
    };

    // 목록이 한 화면에 다 들어오면 전부, 아니면 화면 가운데 위로 올라온 글을 읽음 처리한다
    var inspect = function () {
      queued = false;
      var area = scrollBox.getBoundingClientRect();
      var middle = area.top + area.height / 2;
      var fits = scrollBox.scrollHeight <= scrollBox.clientHeight + 1;
      cardList.querySelectorAll("article.card.unread:not([data-keep])").forEach(function (card) {
        if (fits || card.getBoundingClientRect().top < middle) {
          setCardRead(card, true);
          waiting.add(card.getAttribute("data-id"));
        }
      });
      if (waiting.size) {
        window.clearTimeout(flushTimer);
        flushTimer = window.setTimeout(flush, 500);
      }
    };

    scrollBox.addEventListener(
      "scroll",
      function () {
        if (!queued) {
          queued = true;
          window.requestAnimationFrame(inspect);
        }
      },
      { passive: true }
    );
    window.addEventListener("resize", inspect);
    window.addEventListener("pagehide", flush);
    window.setTimeout(inspect, 250);
  }

  // ---------- 사이드바 폭 조절(PC만): 끌거나 방향키로 바꾸고 쿠키에 기억한다 ----------
  var resizer = document.getElementById("resizer");
  var sidebarBox = document.getElementById("sidebar");
  if (resizer && sidebarBox && window.matchMedia("(min-width: 821px) and (pointer: fine)").matches) {
    var MIN = 220;
    var MAX = 480;
    var STEP = 10;
    var snap = function (px) {
      return Math.min(MAX, Math.max(MIN, Math.round(px / STEP) * STEP));
    };
    var applyWidthClass = function (px) {
      Array.from(body.classList).forEach(function (name) {
        if (/^sw-\d+$/.test(name)) body.classList.remove(name);
      });
      body.classList.add("sw-" + px);
      sidebarBox.style.removeProperty("width");
    };
    var remember = function (px) {
      document.cookie = "sbw=" + px + "; path=/; max-age=31536000; SameSite=Lax";
      applyWidthClass(px);
    };

    resizer.addEventListener("pointerdown", function (event) {
      if (collapsed()) return;
      event.preventDefault();
      body.classList.add("resizing");
      resizer.classList.add("dragging-bar");
      resizer.setPointerCapture(event.pointerId);
    });
    resizer.addEventListener("pointermove", function (event) {
      if (!resizer.hasPointerCapture(event.pointerId)) return;
      var left = sidebarBox.getBoundingClientRect().left;
      sidebarBox.style.width = Math.min(MAX, Math.max(MIN, event.clientX - left)) + "px";
    });
    var finish = function (event) {
      if (!resizer.hasPointerCapture(event.pointerId)) return;
      resizer.releasePointerCapture(event.pointerId);
      body.classList.remove("resizing");
      resizer.classList.remove("dragging-bar");
      remember(snap(sidebarBox.getBoundingClientRect().width));
    };
    resizer.addEventListener("pointerup", finish);
    resizer.addEventListener("pointercancel", finish);
    resizer.addEventListener("dblclick", function () {
      document.cookie = "sbw=; path=/; max-age=0; SameSite=Lax";
      Array.from(body.classList).forEach(function (name) {
        if (/^sw-\d+$/.test(name)) body.classList.remove(name);
      });
    });
    resizer.addEventListener("keydown", function (event) {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      event.preventDefault();
      var delta = event.key === "ArrowRight" ? STEP : -STEP;
      remember(snap(sidebarBox.getBoundingClientRect().width + delta));
    });
  }

  // ---------- 검색과 필터: 입력하면 바로 목록을 고친다 ----------
  var searchForm = document.querySelector("form[role=search]");
  if (searchForm) {
    var queryBox = searchForm.elements.q;
    var filterBox = searchForm.elements.only;
    var typing = null;

    var search = function () {
      var params = new URLSearchParams();
      var text = queryBox.value.trim();
      if (text) params.set("q", text);
      if (filterBox && filterBox.value) params.set("only", filterBox.value);
      var target = searchForm.getAttribute("action") + (params.toString() ? "?" + params : "");
      if (target === window.location.pathname + window.location.search) return;
      window.sessionStorage.setItem("rsshub.refocus", document.activeElement === queryBox ? "1" : "0");
      window.location.href = target;
    };

    queryBox.addEventListener("input", function () {
      window.clearTimeout(typing);
      typing = window.setTimeout(search, 400);
    });
    queryBox.addEventListener("search", search); // 입력 칸의 지우기(x) 버튼
    searchForm.addEventListener("submit", function (event) {
      event.preventDefault();
      search();
    });
    if (filterBox) filterBox.addEventListener("change", search);
    if (window.sessionStorage.getItem("rsshub.refocus") === "1") {
      queryBox.focus();
      queryBox.setSelectionRange(queryBox.value.length, queryBox.value.length);
    }
    window.sessionStorage.removeItem("rsshub.refocus");
  }

  // ---------- 메뉴: 바깥을 누르면 닫는다 ----------
  document.addEventListener("click", function (event) {
    document.querySelectorAll("details.menu[open]").forEach(function (menu) {
      if (!menu.contains(event.target)) menu.open = false;
    });
  });

  // ---------- 화면을 다시 불러와도 보던 자리를 유지한다 ----------
  // 사이드바의 펼침 상태와 스크롤, 같은 화면이면 본문 스크롤까지 기억했다가 되돌린다.
  var UI_KEY = "rsshub.ui";

  function saveUi() {
    var open = {};
    document.querySelectorAll("details.sec[id], details.tree[id], details.acc[id]").forEach(function (box) {
      open[box.id] = box.open;
    });
    var side = document.querySelector(".sb-body");
    var main = document.querySelector(".main .scroll");
    window.sessionStorage.setItem(
      UI_KEY,
      JSON.stringify({
        url: window.location.pathname + window.location.search,
        side: side ? side.scrollTop : 0,
        main: main ? main.scrollTop : 0,
        open: open,
      })
    );
  }

  function restoreUi() {
    var saved = null;
    try {
      saved = JSON.parse(window.sessionStorage.getItem(UI_KEY) || "null");
    } catch (error) {
      saved = null;
    }
    if (!saved) return;
    Object.keys(saved.open).forEach(function (id) {
      var box = document.getElementById(id);
      if (box && saved.open[id]) box.open = true; // 서버가 열어 둔 것은 닫지 않는다
    });
    var side = document.querySelector(".sb-body");
    var main = document.querySelector(".main .scroll");
    if (side) side.scrollTop = saved.side;
    if (main && saved.url === window.location.pathname + window.location.search) {
      main.scrollTop = saved.main;
    }
  }

  window.addEventListener("pagehide", saveUi);
  document.addEventListener("submit", saveUi);
  restoreUi();

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
