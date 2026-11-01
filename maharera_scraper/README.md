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

This tool does not open certificate modals, does not integrate third-party
captcha-solving services, and does not automate CAPTCHA widgets. By default it
enriches each project through the same public-view `authenticatePublic` call
and detail APIs that the IT portal page uses after you open a project
(no separate login account). `robots.txt` on the portal is the
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

## When the HTML listing host does not connect

`maharera.maharashtra.gov.in` is the paginated search. From this network, TCP
to that host connects and the TLS handshake then stalls, so the HTML list
never arrives.

The same authority serves public project details on
`maharerait.maharashtra.gov.in`. That host completes TLS. Its certificate
chain omits the issuer named on the leaf, `GlobalSign GCC R46 OV TLS CA 2025`.
The client downloads that intermediate from GlobalSign's published CA Issuers
URL, checks that OpenSSL can chain it to a root already in the system store,
and only then uses it. With that bundle, this call needs no login and returns
one public project:

`POST /api/maha-rera-public-view-project-registration-service/public/projectregistartion/getProjectGeneralDetailsByProjectId`

Body: `{"projectId": 1}`

`--source auto` (the default) tries the HTML list once. If that connection
times out, it reads a short run of those public project ids instead
(`--max-pages` pages worth, `--start-id` defaults to 1). Fees, document ids,
and user profile ids in that response are not written out.

District can come from the registration number plus the public `getDistrictList`
call (no token). With the default `--enrich-details`, the client also calls
`authenticatePublic` with the shared public-view credentials from the Angular
bundle, then `getProjectLandAddressDetails` and
`getProjectAndAssociatedPromoterDetails` for promoter, taluka, pincode, and
district names. The public CAPTCHA on the page is not required for those API
calls. Use `--no-enrich-details` to skip that step.

```bash
python3 maharera_scraper/scrape_projects.py --source public-view --limit 3
```

A forward proxy you already operate is still available for the HTML list
(`--proxy` or `HTTPS_PROXY`). It only helps when that proxy can finish TLS to
`maharera.maharashtra.gov.in`.

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
