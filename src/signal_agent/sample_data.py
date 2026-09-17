"""A fixed set of realistic articles, used by ``signal demo`` and the tests.

Having a corpus baked into the package means the whole pipeline — clustering,
ranking, summarising, rendering — can be exercised with no network, no API key
and no waiting. It is also what makes the README screenshots reproducible.

The stories are invented. Several of them deliberately appear two or three
times under different outlets and different headlines, so clustering has
something real to find.
"""

from __future__ import annotations

from datetime import timedelta

from .models import Article, utcnow

__all__ = ["sample_articles"]

# (title, outlet, hours_ago, weight, summary)
_RAW: list[tuple[str, str, float, float, str]] = [
    # --- one event, four outlets -------------------------------------------
    (
        "Nvidia unveils Rubin data center GPU with 2x inference throughput",
        "Ars Technica",
        3,
        1.2,
        "Nvidia used its developer conference to announce Rubin, the successor to Blackwell, "
        "claiming roughly double the inference throughput per watt. Shipments are slated for "
        "the second half of next year.",
    ),
    (
        "Nvidia announces Rubin GPU, doubling down on inference",
        "The Verge",
        4,
        1.0,
        "The new Rubin architecture is aimed squarely at inference workloads, where Nvidia has "
        "faced growing pressure from custom silicon built by its own largest customers.",
    ),
    (
        "Nvidia's Rubin chip targets the inference market it helped create",
        "MIT Technology Review",
        5,
        1.25,
        "Analysts read the Rubin launch as a defensive move: the training market is saturating "
        "while inference spending keeps climbing.",
    ),
    (
        "Rubin: Nvidia bets the next era of AI is about serving, not training",
        "Stratechery",
        6,
        1.3,
        "The strategic question is no longer who can train the largest model, but who can serve "
        "one profitably at scale.",
    ),
    # --- one event, three outlets ------------------------------------------
    (
        "EU opens formal antitrust investigation into cloud licensing terms",
        "BBC World",
        7,
        1.2,
        "The European Commission has opened a formal investigation into whether hyperscalers' "
        "licensing terms unfairly penalise customers who run software on rival clouds.",
    ),
    (
        "Brussels launches antitrust probe into cloud software licensing",
        "Politico",
        8,
        1.0,
        "The probe follows three years of complaints from European cloud providers that "
        "licensing terms make switching prohibitively expensive.",
    ),
    (
        "Cloud licensing under formal EU scrutiny after years of complaints",
        "WSJ World",
        9,
        1.15,
        "A finding against the hyperscalers could force changes to licensing worldwide, not just "
        "inside the European Union.",
    ),
    # --- one event, two outlets --------------------------------------------
    (
        "Critical remote code execution flaw found in widely used image library",
        "Ars Technica",
        2,
        1.2,
        "Maintainers have shipped an emergency patch for a heap overflow that can be triggered "
        "by a malicious image. The library ships inside most Linux distributions.",
    ),
    (
        "Emergency patch issued for image library RCE affecting millions of systems",
        "Hacker News",
        2.5,
        1.1,
        "412 points, 188 comments on Hacker News.",
    ),
    # --- singles -----------------------------------------------------------
    (
        "Open source foundation takes over maintenance of abandoned build tool",
        "TechCrunch",
        11,
        1.0,
        "After its sole maintainer stepped back, the widely depended-on build tool has been "
        "adopted by a foundation that will fund two full-time maintainers.",
    ),
    (
        "Rust 1.9x stabilises long-awaited async trait improvements",
        "Ars Technica",
        13,
        1.2,
        "The release closes a gap that has forced library authors into macro workarounds since "
        "async functions landed in the language.",
    ),
    (
        "Developer survey finds AI assistants now write a third of committed code",
        "WIRED",
        10,
        1.0,
        "Respondents reported heavy use of AI coding tools, but also more time spent reviewing "
        "code than a year ago.",
    ),
    (
        "Seed-stage funding rebounds as investors chase applied AI",
        "TechCrunch",
        14,
        1.0,
        "Seed rounds rose for the third consecutive quarter, though later-stage funding remains "
        "well below its peak.",
    ),
    (
        "Enterprise software startup raises $120M Series B to automate compliance",
        "TechCrunch",
        16,
        1.0,
        "The round values the four-year-old company at just over $1B and will fund expansion "
        "into European markets.",
    ),
    (
        "Big tech hiring picks up in infrastructure roles while product teams shrink",
        "The Verge",
        18,
        1.0,
        "Job postings tell a lopsided story: data center and platform roles are up sharply, "
        "while product and design postings continue to fall.",
    ),
    (
        "Regulators approve landmark undersea cable linking three continents",
        "BBC World",
        20,
        1.2,
        "The cable is expected to cut latency between the regions by nearly a third when it "
        "enters service in 2029.",
    ),
    (
        "Central bank holds rates steady but signals cuts if inflation keeps cooling",
        "The Economist",
        6,
        1.25,
        "Policymakers left the benchmark rate unchanged while explicitly opening the door to "
        "easing later in the year.",
    ),
    (
        "Bond markets rally as inflation prints below forecast",
        "WSJ World",
        7,
        1.15,
        "Yields fell across the curve after headline inflation came in two-tenths below "
        "consensus expectations.",
    ),
    (
        "Bank of Canada signals patience as housing costs stay stubborn",
        "CBC Canada",
        12,
        1.1,
        "The governor said shelter inflation remains the main obstacle to returning to target, "
        "even as other components have normalised.",
    ),
    (
        "Canada unveils industrial strategy centred on critical minerals",
        "CBC Canada",
        15,
        1.1,
        "The plan pairs processing subsidies with faster permitting, and has drawn immediate "
        "criticism from provincial governments over jurisdiction.",
    ),
    (
        "India's chip assembly push draws third major manufacturing commitment",
        "NYT World",
        17,
        1.2,
        "The plant will focus on packaging and testing rather than fabrication, a deliberate "
        "step up the ladder rather than a leap to leading-edge manufacturing.",
    ),
    (
        "China's export controls on rare earth processing tighten further",
        "NYT World",
        9,
        1.2,
        "The new rules extend licensing requirements to refining equipment, widening the scope "
        "well beyond the materials themselves.",
    ),
    (
        "UN Security Council session ends without agreement on peacekeeping mandate",
        "BBC World",
        21,
        1.2,
        "Two permanent members signalled they would not support renewal in its current form, "
        "leaving the mandate to expire at the end of the month.",
    ),
    (
        "Kubernetes project deprecates in-tree cloud provider integrations",
        "Hacker News",
        22,
        1.05,
        "260 points, 94 comments on Hacker News.",
    ),
    (
        "Major cloud region suffers four-hour outage after control plane failure",
        "The Verge",
        5,
        1.0,
        "A failed control plane deployment left customers unable to launch instances, though "
        "existing workloads kept running throughout.",
    ),
    (
        "Ransomware group claims breach of regional hospital network",
        "WIRED",
        19,
        1.0,
        "The group posted samples it says came from patient scheduling systems. The network has "
        "confirmed an incident and says clinical systems stayed online.",
    ),
]


def sample_articles() -> list[Article]:
    """The demo corpus, timestamped relative to now so recency ranking works."""
    now = utcnow()
    articles: list[Article] = []

    for index, (title, source, hours, weight, summary) in enumerate(_RAW):
        slug = "".join(c if c.isalnum() else "-" for c in title.lower())[:60].strip("-")
        articles.append(
            Article.create(
                title=title,
                url=f"https://example.{_domain(source)}/{index:02d}/{slug}",
                source=source,
                summary=summary,
                published=now - timedelta(hours=hours),
                origin="demo",
                source_weight=weight,
            )
        )

    return articles


def _domain(source: str) -> str:
    return "".join(c for c in source.lower() if c.isalnum()) or "news"
