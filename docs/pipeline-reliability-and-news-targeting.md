# Pipeline reliability and focused news targeting

## What changed

- Economic AI output must contain all three allocation profiles, finite nonnegative
  weights, and nonempty China/global commentary. Only totals within 100 +/- 2 are
  eligible for rounding adjustment. Invalid syntax or content gets one repair
  attempt; failures retain the market snapshot and are not reused as valid caches.
- Legacy caches marked successful but missing valid allocation profiles are ignored.
- Missing, empty or ambiguous translations are failures, with originals preserved.
  Provider errors log only their class and HTTP status, never arbitrary provider
  text. Successful translations are deduplicated and cached **within one run**.
- Translation batches are 40 titles in the supplied configs; no extra outer retry
  layer was added on top of the existing LiteLLM retries.
- Economic calls have a 60-second aggregate wait budget and per-call timing.
  Background threads are not cancelled on timeout, and dependency imports/AI
  analysis are not hard-bounded by this budget.
- The Yahoo Finance RSS endpoint that returned 404 is disabled in both configs.
  Re-enable it only after verifying that a replacement returns valid RSS/Atom.
- The crawler uses an unbuffered, frozen, no-dev execution command and writes
  non-sensitive degraded-stage summaries to GitHub Actions.
- With DEPLOY_TOKEN configured, the existing reports repository is checked out
  before execution. Recent dated databases and economic files are restored;
  HTML is not restored. The same checkout is reused for publication without a
  token embedded in a Git URL. Missing tokens are an explicit cold-start warning.
  Failed checkout/restoration is best effort and does not block crawling or
  notifications; publishing requires a successful reports checkout.

This retains the current reports-repository persistence design. If that repository
is public, the databases and economic raw responses it already publishes can also
be public. A private state backend and HTML-only publication are recommended as a
separate migration. Configuring supported S3 storage does not automatically move
all economic JSON files there; those stores currently use local output/ paths.

## Which fields actually control news selection?

| File / field | Purpose | Current behavior |
| --- | --- | --- |
| `config/frequency_words.txt` | Match hot-news/RSS titles to topic groups | Active because `filter.method: keyword` |
| `config/config.yaml: rss.feeds[].url` | Decide which RSS articles are collected | Active |
| `config/config.yaml: platforms.sources` | Decide which hot-news sources are collected | Active; source IDs are defined by the upstream API |
| `config/ai_interests.txt` | Semantic relevance/classification preferences | Only used for selection when `filter.method: ai` |
| `config/search_queries.txt` | Actively search for niche news beyond hot lists | Inactive while `web_search.enabled: false` |
| `report.max_news_per_keyword` and group `@N` | Limit displayed results | Do not expand collection coverage |
| `report.rank_threshold` | Highlight high-ranked items | Not a selection threshold |

## Recommended topic priorities

Based on the existing preferences, start with:

1. **Shanghai property:** actual transaction volume/prices, listing discounts,
   inventory, rents/yields, mortgage policy, land auctions. Require both geography
   and a property-related term; bare district names also match unrelated news.
2. **Macro and investable markets:** LPR, CPI/PMI, Fed decisions, employment,
   government-bond yields, currency and gold/oil. Prefer measurable indicators
   and official decisions over generic words such as “market” or “finance”.
3. **AI models/products:** releases, pricing, API changes, open-source licenses,
   enterprise adoption and regulation. Include both Chinese and English aliases.
4. **AI infrastructure/semiconductors:** inference cost, GPU/HBM supply, power,
   advanced packaging and export restrictions.
5. Optional separate profile: **enterprise cloud/SAP**, including BTP, CAP, SAP
   Business AI, Joule, S/4HANA, security advisories and service releases, if useful
   for your work. Do not mix it into the property profile by default.

Reduce broad standalone country terms (“中国”, “美国”, “日本”) and bare district
names. They currently admit unrelated entertainment, accidents and general news.
Use country/geography as required context combined with an industry or policy
term instead. Avoid blanket exclusions such as “广告” if AI ad monetization is
relevant to you.

### Active profile

The active `config/frequency_words.txt` has now been updated directly. Its first
five groups are Shanghai property, national property policy/trends, developer
business events, macro/asset markets, and financial markets. Existing company and
technology interests remain. Country groups now require policy/industry context
rather than matching a country name alone.

No alternative keyword profile is needed. The existing schedule reads this file
by default. For keyword-priority ordering rather than popularity ordering, set
`report.sort_by_position_first: true`.

Keep aliases containing “房”, “经济”, or “市场” for financial groups: the current
economic-news extraction uses group names to identify finance-related news.

### RSS query improvements

The existing company feed joins many company names in one query. That can be
much narrower than intended. Use explicit OR alternatives or separate queries:

- `上海 (二手房 OR 新房) (成交 OR 房价 OR 网签)`
- `房地产 (限购 OR 房贷 OR LPR OR 保交房)`
- `(万科 OR 保利 OR 融创 OR 碧桂园 OR 龙湖) (债务 OR 重组 OR 销售)`

For a Bing RSS URL, URL-encode the entire `q` value and retain `format=RSS`.
Search operators can vary by provider; verify returned titles before replacing
live feeds. For policy coverage, complement aggregators with verified official
sources such as Shanghai housing authorities, PBOC and statistics releases.
Do not assume every official site offers RSS.

Consider `max_age_days: 3` for macro feeds and `7` for property-policy feeds.
The current global one-day setting can discard useful lower-frequency releases.
Keep fast-moving market feeds at one day. Freshness refers to article publication,
not necessarily the observation date of a price or economic indicator.

### Active searches for niche topics

Hot lists cannot reliably cover specific housing or enterprise-cloud questions.
If you enable web search, first configure a supported provider and its key;
`WEB_SEARCH_API_KEY` is now wired into the crawler workflow. An OpenAI-compatible
AI key is not automatically a valid DeepSeek search key.

Candidate additions to `config/search_queries.txt`:

```text
[上海房产政策]
上海 住房 限购 房贷 公积金 最新政策 site:sh.gov.cn
@5
~7d

[上海楼市成交]
上海 二手房 新房 网签 成交量 房价
@8
~3d

[宏观政策与市场]
中国 LPR 央行 货币政策 最新
美联储 利率决议 非农 CPI 最新
@8
~3d

[AI产品与推理成本]
DeepSeek Qwen Claude 模型发布 API 定价 推理成本
@8
~3d
```

The last multi-company query is only a starting point; separate searches by
company if a provider treats the terms as AND and returns too few results.
Web-search results are grouped by search task, not filtered a second time by
`frequency_words.txt`.

## How to validate the next Actions run

1. Check the summary's restored-state file count. The first run of a day can
   legitimately have no current-day DB; later runs should restore it.
2. Confirm a valid economic result has three profiles and each totals 100.
   Later same-day runs should report a valid daily cache hit.
3. Confirm failed translation batches show a class/status and preserve originals.
   The former LiteLLM help message alone does not identify the root cause.
4. Inspect per-source timings and empty-feed messages before changing providers.
5. Review at least 20 matched and 20 rejected titles before activating a narrower
   topic profile; count false positives and important misses.

`report.mode: current` intentionally republishes current matching headlines.
Persistent state repairs “new” detection but does not turn current mode into an
incremental feed. Choose `incremental` for new-only alerts and use a scheduled
`daily` report for a digest if that matches your preference.

## Local validation

```bash
# Full suite; Chromium must already be installed for the browser test.
LITELLM_LOCAL_MODEL_COST_MAP=True uv run --python 3.12 --frozen --no-dev \
  --with pytest --with pytest-playwright python -m pytest -q tests
uv run --frozen --no-dev python -m compileall -q trendradar mcp_server scripts
```

Validated locally on Python 3.12: **76 tests passed, 54 subtests passed**, including
Chromium rendering and best-effort state-restoration workflow checks.
Both edited workflows also passed actionlint. The four test
warnings are dependency/test-tool deprecations, not failed assertions.

These tests use mocks and temporary files; they do not send notifications or push
reports. Live provider reliability, GitHub credentials and protected-branch rules
still require a real Actions run. Dependency alert triage and a private-state
migration remain separate work items.
