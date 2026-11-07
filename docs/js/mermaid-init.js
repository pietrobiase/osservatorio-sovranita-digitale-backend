(function () {
    /*
     * PyMdown Superfences produce questo markup:
     *
     *   <pre class="mermaid"><code>flowchart TD ...</code></pre>
     *
     * Mermaid 10 legge l'innerHTML dell'elemento, quindi il wrapper
     * <code> diventa parte del sorgente del diagramma e il parser
     * fallisce con "Syntax error in text". Sostituire il contenuto
     * con il solo testo dell'elemento rimuove il wrapper prima che
     * Mermaid legga il diagramma.
     */
    function unwrap() {
        document.querySelectorAll(".mermaid").forEach(function (element) {
            if (!element.getAttribute("data-processed")) {
                element.textContent = element.textContent;
            }
        });
    }

    function render() {
        if (!window.mermaid) {
            window.setTimeout(render, 50);
            return;
        }

        unwrap();

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

    /*
     * extra_javascript viene caricato a fine body: il contenuto della
     * pagina è già stato analizzato, quindi il wrapper si può togliere
     * subito, prima di qualunque auto-start di Mermaid.
     */
    unwrap();

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", render);
    } else {
        render();
    }
})();
