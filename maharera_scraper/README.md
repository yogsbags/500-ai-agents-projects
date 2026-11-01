# MahaRERA public project listing

Small Python client for the public registered-projects search on the
Maharashtra Real Estate Regulatory Authority site:

https://maharera.maharashtra.gov.in/projects-search-result

The listing is server-rendered HTML. Each page shows 10 project cards. The
pager links are ordinary GET requests with the form's own parameter names
(`project_name`, `project_location`, `project_state`, `project_district`,
`project_division`, `page`). Choosing a state loads divisions from
`/get-division-data`, and choosing a division loads districts from
`/div-district-data`. Those are the same calls the public search form makes.
There is no public bulk-export file for this list.

This tool does not log in, does not open certificate modals, and does not try
to get past a CAPTCHA or an access check. `robots.txt` on the portal is the
Drupal default: `/projects-search-result` is allowed; `/search/`, `/user/`, and
`/admin/` are not, and this client does not request them.

## Install

```bash
python3 -m pip install -r maharera_scraper/requirements.txt
```

## Sample run

One page (10 cards), written to CSV and JSON in the current directory:

```bash
python3 maharera_scraper/scrape_projects.py --max-pages 1
```

District name. The client asks the public dropdowns for the matching
`project_district` id, sends that id, and also keeps only cards whose District
text matches:

```bash
python3 maharera_scraper/scrape_projects.py --district Pune --max-pages 1
```

Other portal filters:

```bash
python3 maharera_scraper/scrape_projects.py \
  --project-name "GREEN CITY" \
  --project-location 441108 \
  --project-state 27 \
  --project-type registered \
  --max-pages 1 \
  --csv sample.csv \
  --json sample.json
```

`--project-state 27` is Maharashtra (the value in the public state dropdown).
`--project-type revoked` sends `project_type=1` (the Revoked Projects radio).
The default list is Registered Projects, and the portal's own pager omits
`project_type` for that list.

`--max-pages` defaults to 1. `--delay` defaults to 1.5 seconds between
requests. Timeouts and HTTP 429/502/503/504 are retried with backoff
(`--retries`, default 3). Raise `--max-pages` yourself if you want more than
one page. A full registered list is tens of thousands of projects (the public
page has shown on the order of 45,000–50,000 results, 10 per page), so a
complete walk is thousands of requests. Keep the delay.

## Where to run it

Run the sample on a network that can open the listing in a browser. No proxy
is required there. This cloud VM can open TCP to `maharera.maharashtra.gov.in`
(`103.180.31.13:443`) and then the TLS handshake stalls, so the script times
out before any HTML arrives.

A forward proxy helps only when that proxy's own network completes TLS to the
portal. Point `--proxy` or `HTTPS_PROXY` at a proxy you already operate:

```bash
python3 maharera_scraper/scrape_projects.py --max-pages 1 --proxy http://proxy.example:8080
```

There is no proxy configured in this environment. A proxy that uses the same
blocked path fails the same way. The client keeps its identified User-Agent
and the same public listing URL either way.

If the district dropdown cannot be read, a district **name** still filters the
cards that were returned. A numeric `--project-district` is sent as the id
with no name lookup.

## Fields

Each card on the public list becomes one row:

| Field | On the card |
| --- | --- |
| `registration_number` | Registration number, for example `P50500000005` |
| `project_name` | Project name |
| `promoter_name` | Promoter |
| `taluka` | Location line under the name (taluka / city) |
| `district` | District |
| `state` | State |
| `pincode` | Pincode |
| `last_modified` | Last Modified |
| `listing_status` | `registered` or `revoked`, from the active list chip. The card has no separate status column. |
| `certificate_available` | Certificate control is a view link rather than N/A. The PDF modal is not downloaded. |
| `extension_certificate_available` | Extension Certificate is a view link rather than N/A. |
| `latitude`, `longitude` | Coordinates on the public map link, when that link has them |
| `detail_url` | View Details |
| `original_application_url` | View Original Application |
| `source_page_url` | Listing URL that returned the card |

JSON output wraps the rows with `source`, `fetched_at`, the filters actually sent, `reported_total`, and `pages_fetched`. CSV is the rows only.

## Live-site limits

- No bulk download. Only the paginated public list, 10 cards per page.
- Certificate and extension-certificate documents open in a modal (`href="#"`). They are recorded as available or N/A only.
- District and division names depend on `/get-division-data` and `/div-district-data`. Those endpoints have returned HTTP 500/504 while the HTML list was still up. The HTML list can still be filtered by the District text on each card.
- From this development network the scraper cannot finish a request. TCP to `maharera.maharashtra.gov.in` (`103.180.31.13:443`) connects, and the TLS handshake then stalls (TLS 1.2 and TLS 1.3). A sample run exits with:

  `HTTPSConnectionPool(host='maharera.maharashtra.gov.in', port=443): Read timed out.`

  The client stays on that public URL. A fetch of the same URL from another network on 1 Nov 2026 returned the live first page: GREEN CITY 3, promoter GREEN SPACE INFRA VENTURES, taluka Nagpur (Rural), district Nagpur, pincode 441108, last modified 2017-05-20, then the same following cards the public list has shown (UNNATHI WOODS PHASE VII A, MAYFAIR VISHWARAJA, and so on). Offline parsing of that card markup is what the unit tests cover:

```bash
python3 -m unittest discover -s maharera_scraper/tests -v
```

Run that from the repository root. The test module adds `maharera_scraper/` to its import path.
