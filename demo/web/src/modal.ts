// Info modal content. Explains the task and the science for a researcher audience.
// Link hrefs marked TODO are placeholders to fill at deploy time.

export function modalHtml(): string {
  return (
    `<div class="modal-card" role="dialog" aria-modal="true" aria-labelledby="modal-title">` +
    `<button class="modal-close" data-action="close-modal" aria-label="Close">✕</button>` +
    `<h2 id="modal-title">Kraken — operator placement</h2>` +

    `<p class="lede">A hands-on view of <b>Kraken</b>, a placement engine for distributed Complex Event Processing on <b>fog-cloud</b> networks. Continuous queries over geo-distributed event streams run as operators that must be placed on nodes, and each operator must acquire its inputs — either <b>all-push</b> (forward every tuple upward) or <b>push-pull</b> (push the low-rate stream, then pull only the matches). Placement and communication are tightly coupled.</p>` +

    `<h3>Your task</h3>` +
    `<ol class="how">` +
    `<li>Pick a query (the animal tokens).</li>` +
    `<li>Place <b>every</b> operator (sub-query) onto a node — cloud, fog, or a source.</li>` +
    `<li>We compute the <b>tuples transmitted</b> and the <b>latency</b> of your plan, and rank it against four baselines and Kraken on a balanced (cost + latency) score.</li>` +
    `<li>Operators near their sources move fewer tuples; operators near the cloud shorten the path to the sink. Find the balance the Kraken finds.</li>` +
    `</ol>` +

    `<h3>Why joint optimisation wins</h3>` +
    `<p>Existing planners decide placement and communication <i>in stages</i> — fix the placement first, then optimise input acquisition. Committing to a placement early rules out globally better plans. Kraken instead searches over <b>atomic deploy decisions</b>, weighing <i>both</i> communication schemes as it places each operator. In the paper's factory example (a windowed join <span class="mono">[A ∘ B]</span>), all-push moves <b>3010</b> tuples, a staged planner <b>2120</b>, and Kraken <b>360</b> — a plan unreachable when the two decisions are made separately.</p>` +

    `<h3>Headline results</h3>` +
    `<ul class="results">` +
    `<li><b>~3×</b> fewer tuples transmitted vs the sequential baseline (median).</li>` +
    `<li><b>14%</b> lower median transmission latency.</li>` +
    `<li><b>7×</b> faster planning time.</li>` +
    `</ul>` +

    `<h3>About the scoring</h3>` +
    `<p class="fine">Your instant score uses the exact all-push cost model (computed in-browser via Rust/WASM). When a scoring service is available, it is refined with the real push-pull optimiser for an apples-to-apples number. The combined "Kraken score" normalises tuples and latency against this scenario's baselines (0 = as good as the best); Kraken co-optimises communication, which by-hand placement cannot.</p>` +

    `<div class="links">` +
    `<a href="https://doi.org/10.1145/3809431.3812615" target="_blank" rel="noopener">Paper (DEBS '26, DOI)</a>` +
    `<a href="#" data-todo="repo" target="_blank" rel="noopener">Code repository</a>` +
    `<a href="https://bifold.berlin" target="_blank" rel="noopener">BIFOLD</a>` +
    `<a href="https://www.dfki.de" target="_blank" rel="noopener">DFKI</a>` +
    `</div>` +
    `<p class="byline">Ziehn · Glück · Meran · Zeuch · Markl — BIFOLD / TU Berlin / DFKI</p>` +
    `</div>`
  );
}
