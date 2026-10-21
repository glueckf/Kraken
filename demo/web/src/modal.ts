// Info modal content. Explains the task and the science for a researcher audience.
// Link hrefs marked TODO are placeholders to fill at deploy time.

import { t } from "./i18n";

export function modalHtml(): string {
  const s = t();
  return (
    `<div class="modal-card" role="dialog" aria-modal="true" aria-labelledby="modal-title">` +
    `<button class="modal-close" data-action="close-modal" aria-label="Close">✕</button>` +
    `<h2 id="modal-title">${s.modalTitle}</h2>` +

    `<p class="lede">${s.modalLede}</p>` +

    `<h3>${s.yourTask}</h3>` +
    `<ol class="how">` +
    `<li>${s.taskStep1}</li>` +
    `<li>${s.taskStep2}</li>` +
    `<li>${s.taskStep3}</li>` +
    `<li>${s.taskStep4}</li>` +
    `</ol>` +

    `<h3>${s.whyJoint}</h3>` +
    `<p>${s.jointBody}</p>` +

    `<h3>${s.headlineResults}</h3>` +
    `<ul class="results">` +
    `<li>${s.result1}</li>` +
    `<li>${s.result2}</li>` +
    `<li>${s.result3}</li>` +
    `</ul>` +

    `<h3>${s.aboutScoring}</h3>` +
    `<p class="fine">${s.scoringFine}</p>` +

    `<div class="links">` +
    `<a href="https://doi.org/10.1145/3809431.3812615" target="_blank" rel="noopener">${s.linkPaper}</a>` +
    `<a href="#" data-todo="repo" target="_blank" rel="noopener">${s.linkRepo}</a>` +
    `<a href="https://bifold.berlin" target="_blank" rel="noopener">BIFOLD</a>` +
    `<a href="https://www.dfki.de" target="_blank" rel="noopener">DFKI</a>` +
    `</div>` +
    `<p class="byline">Ziehn · Glück · Meran · Zeuch · Markl — BIFOLD / TU Berlin / DFKI</p>` +
    `</div>`
  );
}
