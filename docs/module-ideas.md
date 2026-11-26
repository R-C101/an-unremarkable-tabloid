# Module ideas (researched November 2026)

These are candidate modules for rmdash. Each one is **free**, updates **without a human in the loop**, and reads
well on a **16-grey screen that refreshes every ~30 minutes**. Endpoints were checked with `curl` on 26 Nov 2026.
"Unofficial" means the endpoint is public and stable in practice but undocumented, so it could change.

Popular modules on other e-ink dashboards (TRMNL's plugin list, Inkplate/MagInkDash, Kindle dashboards): calendar,
weather, to-dos, GitHub commit graph, Hacker News, RSS, art or photo of the day, day/year progress and day counters,
word of the day, parcel tracking, transit boards, moon phase.

## Ranked by value for effort

| Module | Source and endpoint | Key | Effort | Notes |
|---|---|---|---|---|
| Cricket (international, IPL, domestic) | ESPN `site.api.espn.com/apis/site/v2/sports/cricket/scorepanel[?dates=YYYYMMDD]` | none (unofficial) | S | Live and scheduled matches. Scores look like `123 (16.5/20 ov, target 210)`. Filter by team name. The team-schedule path returns 404. |
| F1 next race and last podium | jolpica `api.jolpi.ca/ergast/f1/current/next.json`, `/current/last/results.json` | none | S | Race name, circuit, date and time, qualifying |
| On this day / featured article | Wikimedia `api.wikimedia.org/feed/v1/wikipedia/en/onthisday/selected/MM/DD`, `/featured/YYYY/MM/DD` | none (send a User-Agent) | S | New every day |
| Moon phase, moonrise | met.no `api.met.no/weatherapi/sunrise/3.0/moon?lat=&lon=&date=&offset=` or compute locally | none (User-Agent required) | S | Draw the phase as SVG |
| UV index, rain in the next hour | Open-Meteo forecast: `daily=uv_index_max`, `minutely_15=precipitation` | none | S | Extends the existing weather call |
| Exchange rates | Frankfurter `api.frankfurter.dev/v1/latest?base=USD&symbols=INR,EUR` | none | S | ECB daily rates. The old `.app` host redirects. |
| Hacker News top stories | `hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=5` | none | S | Titles and points in one call |
| RSS headlines | Any feed (Google News, BBC, arXiv categories, blogs) | none | S | Let users pick feeds and keyword filters |
| XKCD | `xkcd.com/info.0.json` | none | S | Line art suits 16 greys |
| GitHub contribution graph | GitHub GraphQL `contributionsCollection` | free token | S–M | A heatmap maps naturally to 5 greys |
| Art of the day | Art Institute of Chicago `api.artic.edu/api/v1/artworks/search` (public domain) plus IIIF images | none (send `AIC-User-Agent`) | M | Needs good dithering. Etchings and prints work best. |
| Word of the day | Merriam-Webster RSS `merriam-webster.com/wotd/feed/rss2` | none | S | |
| Stock index close | Yahoo `query1.finance.yahoo.com/v8/finance/chart/%5ENSEI` | none (unofficial, fragile) | S | Daily close and change only |
| Tablet battery in the footer | `/sys/class/power_supply/*/capacity` over the existing SSH session | none | S | |
| Wi-Fi guest QR code | Generated locally (`segno`) | none | S | Never send the Wi-Fi password to a web API |
| Other to-do apps | Todoist `api.todoist.com/api/v1/tasks` (personal token); Microsoft To Do (Graph OAuth) | token / OAuth | M | Same widget as TickTick |
| Strava weekly totals | `www.strava.com/api/v3/athlete/activities` | free OAuth app | M | |
| Parcel tracking | 17track API (free quota) | free key | M | |

## Ideas that need no API

- **Day, week and year progress bars.**
- **A clothing hint** from temperature, rain and AQI ("Jacket. Mask outside.").
- **Match-day mode:** on game day the sports strip grows into a kickoff countdown.
- **A Monday digest:** tasks done last week, results and the AQI trend.
- **Countdowns and birthdays** from config.

## Ruled out

- **CricAPI / cricketdata.org:** needs a key and is capped at about 100 calls a day. ESPN covers cricket without a key.
- **ESPNcricinfo `hs-consumer-api`:** returns 403. NSE India's API sits behind bot protection.
- **NASA APOD with `DEMO_KEY`:** rate-limited and flaky, and photos dither poorly. It works with a free personal key if wanted.
- **Google Fit:** being shut down. Apple Health has no web API.
- **Gmail unread / Google Tasks:** restricted scopes, and refresh tokens for unpublished apps expire after 7 days, so they break unattended refresh.
- **Spotify:** development-mode apps are now heavily restricted.
- **Live tickers** (stocks, crypto): pointless at a 30-minute refresh. A daily price is fine.
