// Local rrweb-compatible recorder shim for Sensei workflow capture.
// Provides window.rrweb.record({ emit }) with a tiny event subset so the
// extension has no remote script dependency under Manifest V3.
(function () {
  if (window.rrweb && typeof window.rrweb.record === "function") return;

  function snapshot() {
    return {
      type: "snapshot",
      href: location.href,
      title: document.title || "",
      text: (document.body && document.body.innerText || "").slice(0, 4000),
      ts: Date.now()
    };
  }

  function selectorFor(el) {
    if (!el || !el.tagName) return "";
    if (el.id) return "#" + String(el.id).replace(/(["\\.#:[\]>+~ ])/g, "\\$1");
    if (el.name) return el.tagName.toLowerCase() + "[name=\"" + String(el.name).replace(/["\\]/g, "\\$&") + "\"]";
    return el.tagName.toLowerCase();
  }

  window.rrweb = {
    record(options) {
      const emit = options && typeof options.emit === "function" ? options.emit : function () {};
      emit(snapshot());
      const onClick = function (event) {
        emit({ type: "click", selector: selectorFor(event.target), x: event.clientX, y: event.clientY, ts: Date.now() });
      };
      const onInput = function (event) {
        emit({ type: "input", selector: selectorFor(event.target), value: String(event.target && event.target.value || "").slice(0, 1000), ts: Date.now() });
      };
      document.addEventListener("click", onClick, true);
      document.addEventListener("input", onInput, true);
      return function stop() {
        document.removeEventListener("click", onClick, true);
        document.removeEventListener("input", onInput, true);
      };
    }
  };
}());
