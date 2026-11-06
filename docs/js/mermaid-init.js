(function () {
    function render() {
        if (!window.mermaid) {
            window.setTimeout(render, 50);
            return;
        }

        window.mermaid.initialize({
            startOnLoad: false,
            theme: "neutral",
            securityLevel: "loose",
            flowchart: {
                useMaxWidth: true,
                htmlLabels: true,
                curve: "basis"
            }
        });

        window.mermaid.run({
            querySelector: ".mermaid"
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", render);
    } else {
        render();
    }
})();
