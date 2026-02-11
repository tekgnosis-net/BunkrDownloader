# CHANGELOG

## v0.9.0 (2026-02-11)

### Feature

* feat: add .pylintrc to configure acceptable code quality standards

- Disable duplicate-code warnings (R0801) for intentional patterns
- Disable too-many-return-statements (R0911) for complex exception handling
- Set max-returns to 8 for methods requiring complex error handling
- Achieves 10.00/10 pylint rating ([`2e9f941`](https://github.com/tekgnosis-net/BunkrDownloader/commit/2e9f941c6c421d819bb63dd10760a78db152f1a9))

## v0.8.1 (2026-02-11)

### Fix

* fix: split long line in _retry_with_backoff method signature

Break method signature across multiple lines to satisfy 100-char line limit ([`f7caf4e`](https://github.com/tekgnosis-net/BunkrDownloader/commit/f7caf4edc519787caab908928fa63415b2744c49))

## v0.8.0 (2026-02-11)

### Feature

* feat: add Bunkr status page maintenance detection with intelligent retry strategies

- Add refresh_server_status() in bunkr_utils.py with TTL-based caching (60s default)
- Implement intelligent retry strategies: backoff (2min, 5min, 10min delays) or skip
- Add --skip-status-check, --status-cache-ttl, --maintenance-strategy CLI flags
- Add STATUS_CHECK_ON_FAILURE, STATUS_CACHE_TTL_SECONDS, MAINTENANCE_RETRY_STRATEGY env vars
- Group failed downloads by subdomain for efficient status checks
- Add log_maintenance_event() for structured logging ([MAINTENANCE] format)
- Add maintenance_detected WebSocket event with toast notifications in frontend
- Update docker-compose.yml and README.md with new configuration options
- Add .github/copilot-instructions.md to .gitignore (local-only file) ([`6a14c6c`](https://github.com/tekgnosis-net/BunkrDownloader/commit/6a14c6c2d2c37ba4d2131b8deeb2cbe2b629cf58))

## v0.7.1 (2026-02-02)

### Documentation

* docs: improve docker compose instructions and add star history ([`840b78a`](https://github.com/tekgnosis-net/BunkrDownloader/commit/840b78ab82a7a3082ee9c8ed574f2970f0d97ebe))

### Fix

* fix: set pull_policy to always in docker-compose ([`c3a0ca8`](https://github.com/tekgnosis-net/BunkrDownloader/commit/c3a0ca8caa5e164d9f94f8071aeee03cc381f634))

### Unknown

* Updated details in README

Removed sections detailing automation workflows for container builds and semantic release processes. ([`a59818b`](https://github.com/tekgnosis-net/BunkrDownloader/commit/a59818b27f5959f6cf29ea7566b336b5ecc80742))

## v0.7.0 (2025-11-18)

### Feature

* feat: allow cancelling downloads and harden fetches ([`5204cfa`](https://github.com/tekgnosis-net/BunkrDownloader/commit/5204cfaaf2371abbe08ae371436f4bfe31b639a2))

## v0.6.2 (2025-11-18)

### Fix

* fix: harden bunkr status handling ([`91bd275`](https://github.com/tekgnosis-net/BunkrDownloader/commit/91bd2752fefa1d81adbc8e12e9e3641532cc3a43))

## v0.6.1 (2025-11-18)

### Fix

* fix: handle missing bunkr status data ([`4cd355b`](https://github.com/tekgnosis-net/BunkrDownloader/commit/4cd355bb328cccba187a51a900515cc6cb027bd9))

## v0.6.0 (2025-11-18)

### Feature

* feat(web): restore progress after reload ([`a5a2fb4`](https://github.com/tekgnosis-net/BunkrDownloader/commit/a5a2fb430c492180c08dcc3dae3502389a825342))

## v0.5.0 (2025-11-18)

### Feature

* feat(web): allow manual websocket refresh ([`6691394`](https://github.com/tekgnosis-net/BunkrDownloader/commit/66913947e10f061d39eb27084d1294cf3da004bc))

### Test

* test: tidy progress smoke tests ([`b445761`](https://github.com/tekgnosis-net/BunkrDownloader/commit/b44576151e7cbdceab84f56bd4024695acabc119))

### Unknown

* Update README.md ([`0bcc2d0`](https://github.com/tekgnosis-net/BunkrDownloader/commit/0bcc2d0dafbe3eb7cb38ecba4acf752c7e7643c5))

* Minor updates. ([`a8325fc`](https://github.com/tekgnosis-net/BunkrDownloader/commit/a8325fcfa819638467a454502d950281814b1b61))

## v0.4.0 (2025-11-17)

### Feature

* feat: improve progress reporting and compose build flexibility ([`71fe767`](https://github.com/tekgnosis-net/BunkrDownloader/commit/71fe7670c8d554130451fdeae4f2ab0080040fa1))

## v0.3.5 (2025-11-17)

### Documentation

* docs: note post-push workflow checks ([`08dadb4`](https://github.com/tekgnosis-net/BunkrDownloader/commit/08dadb45f15756c7ce3ae0960537b220dfb93444))

### Fix

* fix: quiet download progress lint ([`3f96696`](https://github.com/tekgnosis-net/BunkrDownloader/commit/3f96696279a13430c2049d90e3c62aaaaa0e07cb))

## v0.3.4 (2025-11-17)

### Fix

* fix: stabilise progress reporting ([`fe96e77`](https://github.com/tekgnosis-net/BunkrDownloader/commit/fe96e77eb53fbbd55c18e28dcbb0e7ceb328d5d5))

## v0.3.3 (2025-11-17)

### Fix

* fix: unify release version sourcing ([`3f6c98c`](https://github.com/tekgnosis-net/BunkrDownloader/commit/3f6c98c1595a45ea6fc69e8b56556927a36768d4))

## v0.3.2 (2025-11-17)

### Documentation

* docs: align contributing guidance ([`ce4d744`](https://github.com/tekgnosis-net/BunkrDownloader/commit/ce4d744ec3ddec513e313f9f80d5ba4f731ca8d4))

### Fix

* fix: normalise network defaults ([`1f0e2dc`](https://github.com/tekgnosis-net/BunkrDownloader/commit/1f0e2dcbae8279f1fdbcc112629e251ff78c8172))

## v0.3.1 (2025-11-17)

### Fix

* fix: source version from environment ([`7a5e814`](https://github.com/tekgnosis-net/BunkrDownloader/commit/7a5e8146b2e609db3d6a3af511ff25b4ba67d177))

## v0.3.0 (2025-11-17)

### Feature

* feat: allow configuring bunkr endpoints ([`80beda2`](https://github.com/tekgnosis-net/BunkrDownloader/commit/80beda2c4ef8bee86b626f4097e6467d4d6911cd))

## v0.2.1 (2025-11-17)

### Fix

* fix: satisfy pylint arg limit ([`03b634b`](https://github.com/tekgnosis-net/BunkrDownloader/commit/03b634bc4de2e4e7ae95fca2fbc9b6016d99c64b))

## v0.2.0 (2025-11-17)

### Feature

* feat: add configurable logging and ui controls ([`b76d40f`](https://github.com/tekgnosis-net/BunkrDownloader/commit/b76d40f7a3d87a53a71f207c8e379e206ba48c22))

## v0.1.0 (2025-11-17)

### Build

* build: raise chunk warning threshold ([`bd9c483`](https://github.com/tekgnosis-net/BunkrDownloader/commit/bd9c483f9cc1a822da5df79cfeeb5690de18fa6b))

### Feature

* feat: automate releases and surface app version ([`9597483`](https://github.com/tekgnosis-net/BunkrDownloader/commit/9597483d0e7ac6096f386ea9058e91a0114da3f1))

### Fix

* fix: clean issue templates and release workflow ([`791e839`](https://github.com/tekgnosis-net/BunkrDownloader/commit/791e83939a6b6303a053d3e32d07337a79cf5ef8))

* fix: issue templates and release config ([`bc023a5`](https://github.com/tekgnosis-net/BunkrDownloader/commit/bc023a57006c224b934eb3abb54717d210378746))

### Unknown

* Switch to MIT license ([`da4d3db`](https://github.com/tekgnosis-net/BunkrDownloader/commit/da4d3db0ef1e066138344b22990e75505802c378))

* Fix issue templates and clarify readme ([`45a749d`](https://github.com/tekgnosis-net/BunkrDownloader/commit/45a749dfa13c67a78ac27342f28ef40e58b10dd2))

* Update issue templates and docs ([`effa270`](https://github.com/tekgnosis-net/BunkrDownloader/commit/effa270ee015459c229935135b2e91afc7b2cc6b))

* Add web dashboard and container workflow ([`180ea53`](https://github.com/tekgnosis-net/BunkrDownloader/commit/180ea53e205a209b451485ed6ec5b854dcf3f4d4))

* Refactor update_log method to improve readability

- Made `event` and `details` parameters explicit in method call.
- Improved overall code readability by making method invocations more descriptive. ([`f92cece`](https://github.com/tekgnosis-net/BunkrDownloader/commit/f92cece3f7b72c58c8450df8bda52df7fffeb965))

* Add option to disable disk free space check

- Added a command argument to optionally disable the disk free space check
- Enhanced handling of KeyboardInterrupt (CTRL + C) to ensure graceful termination of the process ([`bee3582`](https://github.com/tekgnosis-net/BunkrDownloader/commit/bee35824990034001520dd2f6c4c07b31b935ce7))

* Migrate to src/ structure ([`9ca4f83`](https://github.com/tekgnosis-net/BunkrDownloader/commit/9ca4f83ac27afac3499357faf02be2bd71e13253))

* Delete helpers directory ([`aaf3a36`](https://github.com/tekgnosis-net/BunkrDownloader/commit/aaf3a36116cab47f21bb5469861145782c03b2dc))

* Update README.md ([`dba47c7`](https://github.com/tekgnosis-net/BunkrDownloader/commit/dba47c739e9c5431840fd4401f5d6160744ef128))

* Delete misc directory ([`8d07aaa`](https://github.com/tekgnosis-net/BunkrDownloader/commit/8d07aaa4fe4e5b438e9ccc75bf0b71c845df942d))

* Add files via upload ([`2458d3f`](https://github.com/tekgnosis-net/BunkrDownloader/commit/2458d3f7af39b40f38997ea6f5c23cfa1835b91f))

* Update README.md ([`e872381`](https://github.com/tekgnosis-net/BunkrDownloader/commit/e872381707e206cc0989f3b31fcb7ccd282a8849))

* Update README.md ([`1daa888`](https://github.com/tekgnosis-net/BunkrDownloader/commit/1daa88855fdfb27f725da6791796efd42227b746))

* Refactor for better logical grouping of functions

Moved utility functions to their related modules to improve code organization and maintainability. ([`7f8c89e`](https://github.com/tekgnosis-net/BunkrDownloader/commit/7f8c89ed126d08733789893d6d36fd7c9a1b1565))

* Add support for custom paths during batch download ([`474455b`](https://github.com/tekgnosis-net/BunkrDownloader/commit/474455b009aba626429ab0876f72185afac68d95))

* Update README.md ([`31887e6`](https://github.com/tekgnosis-net/BunkrDownloader/commit/31887e6c550744e13c4a5a0b99599f373136c1ae))

* Add argument to specify download destination

The script now supports a --custom-path argument, allowing users to specify a custom download destination instead of the default location. ([`3b51c41`](https://github.com/tekgnosis-net/BunkrDownloader/commit/3b51c412e1efd888f0f8a2e492caeadfdbabcee2))

* Update issue templates ([`79b9d94`](https://github.com/tekgnosis-net/BunkrDownloader/commit/79b9d946ec7e1bba69fe420088b56f6e62bf5d34))

* Update issue templates ([`01339f4`](https://github.com/tekgnosis-net/BunkrDownloader/commit/01339f446f4398f0b7698b6df5a450dd04f2cbf2))

* Delete .github/ISSUE_TEMPLATE/ISSUE_TEMPLATE directory ([`269199e`](https://github.com/tekgnosis-net/BunkrDownloader/commit/269199e82ed05b4cb583c778a8e25e4cd5acec77))

* Update issue templates ([`c2a490b`](https://github.com/tekgnosis-net/BunkrDownloader/commit/c2a490bb05d5ccf4c04f0f15db5c7fc47900f298))

* Update issue templates ([`577eb05`](https://github.com/tekgnosis-net/BunkrDownloader/commit/577eb05b0e3f182294f9964442d96283e14277ad))

* Delete ISSUE_TEMPLATE directory ([`2aadafb`](https://github.com/tekgnosis-net/BunkrDownloader/commit/2aadafbc6a64f8581f9a34239041cda6e3fb95bf))

* Update issue templates ([`2992fed`](https://github.com/tekgnosis-net/BunkrDownloader/commit/2992fedb113086293e495ee5019f48fb28256781))

* Update issue templates ([`2d01b13`](https://github.com/tekgnosis-net/BunkrDownloader/commit/2d01b138554009174da45c087fe4471a85de8b53))

* Create config.yml ([`c894fe8`](https://github.com/tekgnosis-net/BunkrDownloader/commit/c894fe83c98e99b55d037bf8a02e3a4aebacca69))

* Create bug_report.yml ([`049b601`](https://github.com/tekgnosis-net/BunkrDownloader/commit/049b60154dcd375cc10f68408a53eeed344280f0))

* Delete .github/ISSUE_TEMPLATE/bug_report.md ([`c793d59`](https://github.com/tekgnosis-net/BunkrDownloader/commit/c793d598f9a9436616c0e88b2f2014ec074db0c1))

* Create feature_request.yml ([`8e7ad63`](https://github.com/tekgnosis-net/BunkrDownloader/commit/8e7ad636e224df05855cadb55d0d17790a02404b))

* Delete .github/ISSUE_TEMPLATE/feature_request.md ([`45074cb`](https://github.com/tekgnosis-net/BunkrDownloader/commit/45074cb9c44ef67cff2d0acc6762ce4d093df2e8))

* Update pylint.yml ([`1f5eae9`](https://github.com/tekgnosis-net/BunkrDownloader/commit/1f5eae9e8c216bca4768a141878e719c62943dc9))

* Refactor argument parsing to remove duplication ([`a6ac664`](https://github.com/tekgnosis-net/BunkrDownloader/commit/a6ac664cc06e714e195a03f59bfd8a38ee9ef872))

* Delete .github/workflows/main.yml ([`67cdb4f`](https://github.com/tekgnosis-net/BunkrDownloader/commit/67cdb4f15cb80a65dfb0f911bd4f5d72b78592a0))

* Create pylint.yml ([`361e975`](https://github.com/tekgnosis-net/BunkrDownloader/commit/361e975cf1bf21a613e63152a130a81a6349bc5b))

* Create main.yml ([`d52c150`](https://github.com/tekgnosis-net/BunkrDownloader/commit/d52c15041a88ae013dcb104ce512dc8c77119699))

* Create CONTRIBUTING.md ([`f8a81a8`](https://github.com/tekgnosis-net/BunkrDownloader/commit/f8a81a834248bd7ca9a0e872969c0e3f4e12b991))

* Move dataclass to config module ([`d7f34aa`](https://github.com/tekgnosis-net/BunkrDownloader/commit/d7f34aac0ccaf0461c7ed30ab9b844aa4e06d27a))

* Fix logger table sizing and add color constants

- Adjust logger table to better handle panel widths in line with other managers
- Add constants for colors used across all managers ([`649da94`](https://github.com/tekgnosis-net/BunkrDownloader/commit/649da94f78a1d9daa8d1a64b90c9550add49df5a))

* Adapt UI to terminal size ([`3953182`](https://github.com/tekgnosis-net/BunkrDownloader/commit/395318259c91f70140e4698d3e3347b6edd76491))

* Update issue templates ([`91c9b87`](https://github.com/tekgnosis-net/BunkrDownloader/commit/91c9b873dbee702c08d97ea781bf46915b6e16b8))

* Update issue templates ([`004e804`](https://github.com/tekgnosis-net/BunkrDownloader/commit/004e80424e0f350522033dd6412077e8f759fc03))

* Update issue templates ([`93da6f2`](https://github.com/tekgnosis-net/BunkrDownloader/commit/93da6f28fc538d9f86bf261a182cabf49bf8a55f))

* Ignore empty lines in URLs.txt

Previously, empty lines in URLs.txt would cause issues during processing. This update strips whitespace and filters out blank entries so that only valid URLs are passed to the downloader. ([`0bfca5e`](https://github.com/tekgnosis-net/BunkrDownloader/commit/0bfca5eb448ca667d78f199f6e630eef7f9f1b9d))

* Update downloader.py ([`e5e695c`](https://github.com/tekgnosis-net/BunkrDownloader/commit/e5e695c60ead617b428ebb92b5d8a2c9c34751a0))

* Improve handling of paginated album pages ([`098fb6a`](https://github.com/tekgnosis-net/BunkrDownloader/commit/098fb6ad0d295d61183bd0ec15340465559e0998))

* Fix handling of paginated album pages ([`7616e4c`](https://github.com/tekgnosis-net/BunkrDownloader/commit/7616e4ca2f2d70a5b5826e3c81ca2c6ba71a3ee1))

* Update requirements.txt ([`f22e8cd`](https://github.com/tekgnosis-net/BunkrDownloader/commit/f22e8cd5c5401fa6311cd2ba601a7a17996422af))

* Add support for paginated album pages

Previously, only the first album page was processed.
This update introduces pagination support, allowing the scraper to fetch and extract item pages from all subsequent album pages as well. ([`1197bee`](https://github.com/tekgnosis-net/BunkrDownloader/commit/1197beec11c42b216ee385a92a4d63671bdafd57))

* Add handling for ChunkedEncodingError causes

Update save_file_with_progress to catch ChunkedEncodingError and mark downloads as failed when they are interrupted.
Handles IncompleteRead and ConnectionResetError (wrapped inside ChunkedEncodingError), allowing partial files to be retried during the final synchronous attempt. ([`0e7e1a0`](https://github.com/tekgnosis-net/BunkrDownloader/commit/0e7e1a04f592317c4c963c12aa6bd640da60f153))

* Refactor config.py and minor code fixes

- Reorganized config.py into clearer sections (Paths, API, Regex, Download, HTTP, Data Classes)
- Replaced HTTP status constants with IntEnum for better readability
- Abbreviated and clarified comments for conciseness
- Added type hints where beneficial
- Applied minor fixes and improvements in related parts of the code ([`6ca9a45`](https://github.com/tekgnosis-net/BunkrDownloader/commit/6ca9a45686e47635bbdb4fac277556f888f0631f))

* Fix encoding issue for Russian letters ([`987cb31`](https://github.com/tekgnosis-net/BunkrDownloader/commit/987cb31cd893978265a9f00a39ebef792a4726e3))

* Update requirements.txt ([`2f270a6`](https://github.com/tekgnosis-net/BunkrDownloader/commit/2f270a61ae4c07c0da4d40be38ebf54ba1984521))

* Update main.py ([`a221040`](https://github.com/tekgnosis-net/BunkrDownloader/commit/a2210402340e2dc2be5fb1de85c53daa4c9a83fc))

* Refactor: improve types &amp; disk space const

- Fixed and refined type annotations for clarity.
- Introduced a new constant to represent disk space usage.
- Refactored related code to use the new constant consistently. ([`636c8e0`](https://github.com/tekgnosis-net/BunkrDownloader/commit/636c8e03bd8140ce41f59efaba4ee816684856f6))

* Check disk space in working dir

Fixed check_disk_space() to use the script’s working directory instead of root,  preventing false “Insufficient disk space” errors on other drives. ([`9a8c688`](https://github.com/tekgnosis-net/BunkrDownloader/commit/9a8c6880219df085b1f936eb6425e8a71dbdd484))

* Delete file_utils.py ([`2d8d6ad`](https://github.com/tekgnosis-net/BunkrDownloader/commit/2d8d6adc69f1964b8cce98632ad0c1860c37afd3))

* Fix disk space check when running from external drives

Refactored to return the correct root based on the working directory, fixing issues when running from external drives ([`d41c3d4`](https://github.com/tekgnosis-net/BunkrDownloader/commit/d41c3d491a42da1ef076988e14162ece520ee57f))

* Improve disk space check ([`4129fb7`](https://github.com/tekgnosis-net/BunkrDownloader/commit/4129fb7171ce2dda2da62e77e6f0dc21be853c31))

* Improve log message for insufficient disk space ([`5abad3a`](https://github.com/tekgnosis-net/BunkrDownloader/commit/5abad3a299d93a37dcca304603d9d1302e22660e))

* Update requirements.txt ([`62b970e`](https://github.com/tekgnosis-net/BunkrDownloader/commit/62b970e9403d11c40e47e5f838f0dd78807ce7ad))

*  Improve checks and logging before download

This update introduces the following improvements to the code:
- Added a check for the current Python version before download;
- Verified available disk space to ensure sufficient capacity;
- Improved clarity and consistency of log messages;
- Renamed some variables for better readability. ([`9ff7e55`](https://github.com/tekgnosis-net/BunkrDownloader/commit/9ff7e55497fc46e2a4b47a32873661f8a7748ed2))

* Improve media slug extraction ([`6dd0711`](https://github.com/tekgnosis-net/BunkrDownloader/commit/6dd0711a5fc58364731351d56613b5b3da323bd8))

* Update script to adapt to recent website changes

Remove unnecessary function for extracting media slug ([`ee1a862`](https://github.com/tekgnosis-net/BunkrDownloader/commit/ee1a8625504f71cfd2625ff9a0d4c9dbb122520b))

* Minor readability improvements ([`4cce646`](https://github.com/tekgnosis-net/BunkrDownloader/commit/4cce646f1763aff7f4ed1d4594c5eb4af65dc7ce))

* Fix slug extraction for media URLs with filenames

Previously, the script only supported URLs of the form /a/&lt;album_id&gt; or /f/&lt;file_id&gt;. This update improves slug detection by extracting the filename from the last URL segment when present (e.g., &#39;filename.jpg&#39;), with a fallback to parsing &lt;script&gt; tags if needed. ([`42da5f0`](https://github.com/tekgnosis-net/BunkrDownloader/commit/42da5f00ab671a60d681a5a8eae0caf28b41d323))

* Update the domain on 403 errors ([`eb97b8d`](https://github.com/tekgnosis-net/BunkrDownloader/commit/eb97b8d6e280e893bcfe6af5c8a8155d15db0661))

* Update general_utils.py ([`0e71eb4`](https://github.com/tekgnosis-net/BunkrDownloader/commit/0e71eb469ba2f4978b0280f73457ee73f7aca45f))

* Update config.py ([`e385de8`](https://github.com/tekgnosis-net/BunkrDownloader/commit/e385de820adcd1c79b11da062d69a4e8c258ff86))

* Update general_utils.py ([`06a441a`](https://github.com/tekgnosis-net/BunkrDownloader/commit/06a441a601b284a48fe8c22b53853fc22c1ca4a2))

* Update config.py ([`b8e1f37`](https://github.com/tekgnosis-net/BunkrDownloader/commit/b8e1f373253daa8d8ab907567c9ab028ce95987b))

* Update general_utils.py ([`74fe0b2`](https://github.com/tekgnosis-net/BunkrDownloader/commit/74fe0b2decc6113c25c8e6205b8cdd5ae808df9c))

* Add functions to truncate overly long filenames

- Added `remove_invalid_characters` to clean filenames by removing invalid characters.
- Added `truncate_filename` to ensure filenames do not exceed the maximum byte length limit, preventing OSError [Errno 36]. ([`b50101e`](https://github.com/tekgnosis-net/BunkrDownloader/commit/b50101e8dc15c759f9623d9ccfbafad70f99efd6))

* Add dataclasses for recurrent info

- Added DownloadInfo to represent download task details.
- Added SessionInfo to hold session-related data.
- Added AlbumInfo to store album details and associated item pages.
- Refactored code to use the new dataclasses, improving readability and maintainability.
- Made minor improvements to variable names and code structure for better clarity. ([`652580a`](https://github.com/tekgnosis-net/BunkrDownloader/commit/652580aac6aba2247cdf48ea0570760e7fb75c3b))

* Fix encoding issues and improve decryption

- Ensure proper UTF-8 handling by using `bytearray` and `.decode(errors=&#34;ignore&#34;)`  
- Fix emoji corruption by re-encoding with `latin1` before decoding as UTF-8  
- Improve filename formatting to handle special characters correctly ([`f9f3728`](https://github.com/tekgnosis-net/BunkrDownloader/commit/f9f3728f0a7c9a7cfc7fe8ae17ba8bf961941b8e))

* Update README.md ([`6cf862a`](https://github.com/tekgnosis-net/BunkrDownloader/commit/6cf862ac1d9ea248e6369630358f9716512519e0))

* Refactor UI handling to remove redundancy.

- Simplified UI handling by using `nullcontext()` when `disable_ui` is set. ([`a67c6ea`](https://github.com/tekgnosis-net/BunkrDownloader/commit/a67c6eaa6f2fce8a265549758c1a49de50a07ba8))

* Update README.md ([`fba19a6`](https://github.com/tekgnosis-net/BunkrDownloader/commit/fba19a6a6835f93929c37ec24d7206313bf14fff))

* Update README.md ([`29e2809`](https://github.com/tekgnosis-net/BunkrDownloader/commit/29e28092176af5fdc456232f92621e8005c8a2a3))

* Update README.md ([`8a85b37`](https://github.com/tekgnosis-net/BunkrDownloader/commit/8a85b378eb53bfc873a4351f8c9e5a826bec6f05))

* Add support to disable UI output in Notebooks

When the --disable-ui argument is used, the script suppresses the progress bar and minimizes log messages, preventing crashes due to excessive output in notebook environments. ([`05e0639`](https://github.com/tekgnosis-net/BunkrDownloader/commit/05e0639710aee35a234d7dc078d746ce05b2791f))

* Improve readability of API response handling

- Made decryption process clearer with better variable names and structure
- Added meaningful logging for missing or invalid response data ([`0cd94ef`](https://github.com/tekgnosis-net/BunkrDownloader/commit/0cd94ef1950efaf00758704e057a940561572980))

* Update crawler_utils.py ([`c8c0625`](https://github.com/tekgnosis-net/BunkrDownloader/commit/c8c06252dd281ea942372c1c1d6dfa0f48512105))

* Update url_utils.py ([`67c3d42`](https://github.com/tekgnosis-net/BunkrDownloader/commit/67c3d42261b43e7566b1d1e2391dda01842bb6e4))

* Adapt to latest site changes

Adapt to site changes with API update and decryption fix. ([`36b272d`](https://github.com/tekgnosis-net/BunkrDownloader/commit/36b272d25607f5cf491e83ad43bd269929286467))

* Reduce sleep time and add concurrency constant

Reduce sleep time between album download attempts and introduce constant for concurrent tasks. ([`7c228b8`](https://github.com/tekgnosis-net/BunkrDownloader/commit/7c228b89bc15fe49dd3a5ece53de8668135cce65))

* Update download_utils.py

Refactored code to use the new constants. ([`4d472dd`](https://github.com/tekgnosis-net/BunkrDownloader/commit/4d472dda14d3a5e12e04d2b6d8d6ad9601eca6a7))

* Define thresholds and chunk sizes with improved granularity

- Defined file size thresholds and corresponding chunk sizes for more efficient file downloads.
- Increased chunk sizes for medium to large files to reduce overhead.
- Added additional thresholds for better granularity in handling a wider range of file sizes. ([`af54043`](https://github.com/tekgnosis-net/BunkrDownloader/commit/af5404320468a9755e4851102714b16d01b1483c))

* Update download_utils.py

Adjusted comments. ([`1ffedaa`](https://github.com/tekgnosis-net/BunkrDownloader/commit/1ffedaaa6a73155a82491d7778254fe488fe747b))

* Update download_utils.py

Fix file lock issue by ensuring the file is closed before moving. ([`a64da7d`](https://github.com/tekgnosis-net/BunkrDownloader/commit/a64da7de1da8256700b8bfba86717c9099ce1588))

* Update general_utils.py ([`5083a07`](https://github.com/tekgnosis-net/BunkrDownloader/commit/5083a07ed261bc822f16bb40153322315f57fb21))

* Refactor code for Ruff compliance

Updated codebase to follow Ruff linter&#39;s recommendations and formatting rules. 
Refactored various sections to improve readability and ensure consistent styling. ([`d29bed2`](https://github.com/tekgnosis-net/BunkrDownloader/commit/d29bed2e1fae78d78dd478ded72e5194e8a30f48))

* Refactor code for Ruff compliance

Updated codebase to follow Ruff linter&#39;s recommendations and formatting rules. 
Refactored various sections to improve readability and ensure consistent styling. ([`4bfb686`](https://github.com/tekgnosis-net/BunkrDownloader/commit/4bfb6869cc6fa889066629b88309a2faca36a521))

* Update log message for partial download

Modified the log message to indicate that the file&#39;s extension was changed to &#39;.temp&#39; due to partial download. ([`f5d9f69`](https://github.com/tekgnosis-net/BunkrDownloader/commit/f5d9f698935166e35af31d85d017a312b2125e0d))

* Add &#39;.temp&#39; extension for partial downloads

Modified the download logic to append &#39;.temp&#39; to the filename if the download is partial. ([`04a155b`](https://github.com/tekgnosis-net/BunkrDownloader/commit/04a155b55facaac578ca7afb07820a8787553c8b))

* Update log_manager.py

Adjusted log panel widht. ([`9635232`](https://github.com/tekgnosis-net/BunkrDownloader/commit/96352323932171a3e77357f11c360094b99ca662))

* Update media_downloader.py ([`306aaa9`](https://github.com/tekgnosis-net/BunkrDownloader/commit/306aaa99c2ff45bd0031a4c9914539f844013fa8))

* Update README.md ([`d6db5bb`](https://github.com/tekgnosis-net/BunkrDownloader/commit/d6db5bbd84cc5b9b8342365fd7bfe8b9ddd71938))

* Update general_utils.py ([`1e6dc3e`](https://github.com/tekgnosis-net/BunkrDownloader/commit/1e6dc3edd6bb4e3fa53d7afa605e1dfebc78497c))

* Update download_utils.py

Implement logic to handle partial downloads. ([`7631688`](https://github.com/tekgnosis-net/BunkrDownloader/commit/76316889d075fb90979026b7c31e5fd4ddcd792e))

* Update download_utils.py

Implement logic to handle partial downloads. ([`d13eee2`](https://github.com/tekgnosis-net/BunkrDownloader/commit/d13eee2639753527612aa785d32c8079fc9986aa))

* Update download_utils.py

Implement logic to handle partial downloads. ([`b1450c8`](https://github.com/tekgnosis-net/BunkrDownloader/commit/b1450c8234bde40f6759b2a10c0989a8de8f6086))

* Update media_downloader.py

Implement logic to handle partial downloads and 502, 521 errors. ([`2fc4264`](https://github.com/tekgnosis-net/BunkrDownloader/commit/2fc426404120ea08086b8e92b35e8a6d18c6d78d))

* Update crawler_utils.py

Fallback to extracting download link as non-media file if standard link is unavailable. ([`d2b4d4e`](https://github.com/tekgnosis-net/BunkrDownloader/commit/d2b4d4e089bed4d7b637833ec842e3e4ba26c706))

* Update general_utils.py

Add function to validate download link by checking for 521 errors. ([`16afea1`](https://github.com/tekgnosis-net/BunkrDownloader/commit/16afea18f250365340a436a64309aeea37dd9865))

* Update crawler_utils.py

Improve format_item_filename to handle cases where the original filename is contained in the URL-derived filename. ([`6e8744e`](https://github.com/tekgnosis-net/BunkrDownloader/commit/6e8744e74e204f6d9847f2ae85964cfa848b31d5))

* Update media_downloader.py

Refactor skip_file_download by implementing helper function to avoid code repetition. ([`fc16c84`](https://github.com/tekgnosis-net/BunkrDownloader/commit/fc16c841b1386a3b1a92ef80d4bd1a807428431e))

* Update crawler_utils.py

Implemented filename formatter to combine actual filename and URL-based filename. ([`1950860`](https://github.com/tekgnosis-net/BunkrDownloader/commit/195086011bf2be2d9b35217b40a105dc50bcaafc))

* Update url_utils.py ([`f015a94`](https://github.com/tekgnosis-net/BunkrDownloader/commit/f015a94e2f03591fcbcde8d72a67dabaefbeec3b))

* Update url_utils.py ([`105503a`](https://github.com/tekgnosis-net/BunkrDownloader/commit/105503af843ddec2b3eeb3a97ba325c4d5d8d3e2))

* Update crawler_utils.py

Updated the filename extraction logic to retrieve the actual filename of the file. ([`302eb96`](https://github.com/tekgnosis-net/BunkrDownloader/commit/302eb9653a6e2cec6290a7edaf3da37179c5eccb))

* Update README.md ([`483b65b`](https://github.com/tekgnosis-net/BunkrDownloader/commit/483b65b199ce15f5c6a44357fcc2bb393f00b85c))

* Update media_downloader.py ([`26ae3e1`](https://github.com/tekgnosis-net/BunkrDownloader/commit/26ae3e11a0662f848e3657a6222ea3fd375c240a))

* Update downloader.py

Add support for selective file downloading based on filename criteria. ([`895b078`](https://github.com/tekgnosis-net/BunkrDownloader/commit/895b07878d2473ac15eb04d902d62be33d9fd060))

* Update album_downloader.py

Add support for selective file downloading based on filename criteria. ([`66e0507`](https://github.com/tekgnosis-net/BunkrDownloader/commit/66e05077860d6613afa584660ed0ba4a11113b7e))

* Update media_downloader.py

Add support for selective file downloading based on filename criteria. ([`b79c72a`](https://github.com/tekgnosis-net/BunkrDownloader/commit/b79c72a8cba7e2b20c1f034c714a252313b893a3))

* Update downloader.py

Add support for selective file downloading based on filename criteria. ([`a926945`](https://github.com/tekgnosis-net/BunkrDownloader/commit/a926945dd8bb3a29a1bfbc190584fd8db9af0d6e))

* Update README.md ([`6035db6`](https://github.com/tekgnosis-net/BunkrDownloader/commit/6035db61176a8d83659c2fe1c8e7226caf79e077))

* Update README.md ([`2d22c91`](https://github.com/tekgnosis-net/BunkrDownloader/commit/2d22c91da995e113becaf6589b75d38d2696ee02))

* Update README.md ([`f4e325e`](https://github.com/tekgnosis-net/BunkrDownloader/commit/f4e325e6eadc74ed88c23d6b75f013e1f9aa87dd))

* Update README.md ([`06dd683`](https://github.com/tekgnosis-net/BunkrDownloader/commit/06dd6834a50c2c01611a76657c2fe5b6429aca9d))

* Update README.md ([`d432c8d`](https://github.com/tekgnosis-net/BunkrDownloader/commit/d432c8d754f50c488bee32d76471cd4e7eecebdd))

* Update README.md ([`f384951`](https://github.com/tekgnosis-net/BunkrDownloader/commit/f384951051fef5d19daab192cdee03d838daf46f))

* Update README.md ([`bad9d1d`](https://github.com/tekgnosis-net/BunkrDownloader/commit/bad9d1daeb39b4753c1a51b7ec41dcd07c55a0de))

* Update README.md ([`9a215dc`](https://github.com/tekgnosis-net/BunkrDownloader/commit/9a215dc4390394cfc284b0282b92483d65e5a86e))

* Update downloader.py

Refactor code to align with new directory structure of the project. ([`f53f06d`](https://github.com/tekgnosis-net/BunkrDownloader/commit/f53f06ddade4e5b6eb3893ff7ec44b79c310bec4))

* Add files via upload

Create downloaders directory to group album and single media downloaders with utilities for better modularity

- Moved album and single media downloader classes into the downloaders directory.
- Grouped related download utilities within the same directory for improved logical structure and modularity. ([`a600b83`](https://github.com/tekgnosis-net/BunkrDownloader/commit/a600b83321cf030e2db543c553174b70e40daf18))

* Delete helpers/download_utils.py ([`e92f601`](https://github.com/tekgnosis-net/BunkrDownloader/commit/e92f6012965dc397497db48f16d3cb288f4db251))

* Update __init__.py ([`492c488`](https://github.com/tekgnosis-net/BunkrDownloader/commit/492c488b1d2af68d941098cd96b3705e443f0744))

* Update README.md ([`54573ff`](https://github.com/tekgnosis-net/BunkrDownloader/commit/54573ff196ff82e51d6f9c5740b5cbb3d5e66216))

* Update README.md ([`cc51e38`](https://github.com/tekgnosis-net/BunkrDownloader/commit/cc51e385e641cc575f462338ba71b9dcae526da4))

* Update README.md ([`4b1f422`](https://github.com/tekgnosis-net/BunkrDownloader/commit/4b1f422afa05ae7d285c2deeff773442f98d8054))

* Update README.md ([`90767b3`](https://github.com/tekgnosis-net/BunkrDownloader/commit/90767b3d79e95171991e40de9d3bee867ccdf04b))

* Update downloader.py

Updated the script to implement a method in the MediaDownloader class that skips downloading a file from an album if its filename contains at least one word from the ignore list. The ignore list is specified through the --ignore argument option in the command line. ([`9545d23`](https://github.com/tekgnosis-net/BunkrDownloader/commit/9545d23b4c7c751cc4cd672aa3a649005ff17313))

* Update general_utils.py

Added a function to sanitize the directory name. ([`05d857e`](https://github.com/tekgnosis-net/BunkrDownloader/commit/05d857ebbb0bd442714edb11666f5a430e5b296f))

* Update README.md ([`89d4e12`](https://github.com/tekgnosis-net/BunkrDownloader/commit/89d4e12dfad8a7dd1c3bc531867e06653d7be71f))

* Update requirements.txt

Removed Playwright from the required packages list. ([`4f677a9`](https://github.com/tekgnosis-net/BunkrDownloader/commit/4f677a9cefe8bc5272d679fe3d5d520840b3717f))

* Update url_utils.py

Removed unnecessary functions. ([`a7bdb22`](https://github.com/tekgnosis-net/BunkrDownloader/commit/a7bdb227671f237b41b16e87c424044079791791))

* Update config.py ([`b9518e2`](https://github.com/tekgnosis-net/BunkrDownloader/commit/b9518e2bc740ee73fc882d531958b970e93b4432))

* Update __init__.py ([`02e9710`](https://github.com/tekgnosis-net/BunkrDownloader/commit/02e9710d013b6bbcbcbe101bd844eb9ec6bdc187))

* Update crawler_utils.py ([`3e2cc99`](https://github.com/tekgnosis-net/BunkrDownloader/commit/3e2cc9920d6356a0685ec75271c874488c91ae04))

* Delete helpers/crawlers/playwright_crawler.py ([`8954cf7`](https://github.com/tekgnosis-net/BunkrDownloader/commit/8954cf75fcbaf357f5a8b56f5788cbea97c2650a))

* Update downloader.py ([`34bcf84`](https://github.com/tekgnosis-net/BunkrDownloader/commit/34bcf84e16d58e89c01314f2824b8397cb55ab9b))

* Update main.py ([`c73f461`](https://github.com/tekgnosis-net/BunkrDownloader/commit/c73f461181e7fc1e50feaa0a619b93c6cfaa5f02))

* Update url_utils.py

Fix album name handling to correctly decode HTML entities

- Implemented `html.unescape` to decode HTML entities (like &amp;amp) to their actual characters.
- Ensured album names are cleaned and displayed properly. ([`dfb9f5e`](https://github.com/tekgnosis-net/BunkrDownloader/commit/dfb9f5e65d6984e40022fc3a0d95a6f96dc7ede5))

* Update crawler_utils.py ([`bb20a36`](https://github.com/tekgnosis-net/BunkrDownloader/commit/bb20a36a2a022c165564ecba96521953672dcc0f))

* Update url_utils.py

Update module to handle new URL format of the site

- Adjusted functions to accommodate the updated URL structure.
- Fixed parsing logic for extracting download links based on the new format. ([`e7b550a`](https://github.com/tekgnosis-net/BunkrDownloader/commit/e7b550a1c8db1dea117b23fc8b553997e14e8e99))

* Update downloader.py ([`2bf9f41`](https://github.com/tekgnosis-net/BunkrDownloader/commit/2bf9f41d4fd18033c063e948c6143ae9da151b56))

* Update general_utils.py

Added an error message pertaining to the 502 Bad Gateway status. ([`9a9b652`](https://github.com/tekgnosis-net/BunkrDownloader/commit/9a9b652a23ee3c5f3d87694913fa93a9e5bea862))

* Update general_utils.py

Added the format_directory_name function to generate a formatted directory name according to the template &#39;&lt;album_name&gt; (&lt;album_id&gt;)&#39;, where &lt;album_name&gt; is the site-specific album name (non-unique) and &lt;album_id&gt; is the unique identifier of the album. ([`b8ff108`](https://github.com/tekgnosis-net/BunkrDownloader/commit/b8ff1088c7d510300e07febec485ca957104457b))

* Update url_utils.py

Added the function get_album_name to extract the original album name. ([`6a8958f`](https://github.com/tekgnosis-net/BunkrDownloader/commit/6a8958f4dc55250e353adfe0ef9dab24bc8b659c))

* Update downloader.py

Updated code to use the format_directory_name function to create download directories names in the format &#34;&lt;album_name&gt; (&lt;album_id&gt;)&#34;, where &lt;album_name&gt; is the site-specific album name (non-unique) and &lt;album_id&gt; is the unique identifier of the album. ([`b293ec4`](https://github.com/tekgnosis-net/BunkrDownloader/commit/b293ec4d25f30ee8c7603823e2556dc9b0d769af))

* Update main.py ([`ba9eea9`](https://github.com/tekgnosis-net/BunkrDownloader/commit/ba9eea99c90dfd2de5d5801306f6332c71d67f34))

* Update downloader.py ([`29cc30c`](https://github.com/tekgnosis-net/BunkrDownloader/commit/29cc30c7cb6f846fc367ecdacb9415dfdbbe53d9))

* Update playwright_crawler.py ([`467edd4`](https://github.com/tekgnosis-net/BunkrDownloader/commit/467edd402275a705faa0b3cec677c9317b3c2ec7))

* Add files via upload

Add &#39;config.py&#39; as a centralized configuration module for managing constants and settings used across the project ([`1a4c3d4`](https://github.com/tekgnosis-net/BunkrDownloader/commit/1a4c3d4c30ea499fb1aee76e2e21788a2ae58c17))

* Update main.py ([`55ed42a`](https://github.com/tekgnosis-net/BunkrDownloader/commit/55ed42a8e3438d24e3fc18cfa2ca33c018f97ed2))

* Update downloader.py ([`37cb02a`](https://github.com/tekgnosis-net/BunkrDownloader/commit/37cb02ac57baf0e0d30f9b5706b275ef4b38431a))

* Update live_manager.py

Added execution time tracking and log messages for script start and completion

- Implemented functionality to compute and display the execution time of the script.
- Added a start message in the log table when the script begins execution.
- Added a completion message in the log table showing the execution time. ([`ecbe5ea`](https://github.com/tekgnosis-net/BunkrDownloader/commit/ecbe5eac13ce5c3d7efa6b3e756d7a1ddf222894))

* Update progress_manager.py

Implement buffer for overall progress bar and enhance code organization

- Added a buffer to the overall progress bar to limit the maximum number of visible overall tasks.
- Reorganized code by grouping static methods and private methods towards the end of the class for improved readability and maintainability. ([`d4473f5`](https://github.com/tekgnosis-net/BunkrDownloader/commit/d4473f55bdab25b70937c087ed4279559ecb25d3))

* Update log_manager.py ([`3fe36a5`](https://github.com/tekgnosis-net/BunkrDownloader/commit/3fe36a5104ce82423393aa2036dcb07d6a2a042e))

* Update live_manager.py ([`1068e66`](https://github.com/tekgnosis-net/BunkrDownloader/commit/1068e660396b77ab810ecc6db6c32b3e53c4caf2))

* Update downloader.py ([`dfe1eae`](https://github.com/tekgnosis-net/BunkrDownloader/commit/dfe1eaed6611bc0444276255b23bb99303873efb))

* Update progress_manager.py ([`f08fb98`](https://github.com/tekgnosis-net/BunkrDownloader/commit/f08fb9870d63d685dbc1e2a5e4c6f305823dba7a))

* Update downloader.py ([`4f52219`](https://github.com/tekgnosis-net/BunkrDownloader/commit/4f52219308ecf247cb5834518de8d7b01d95a28a))

* Update progress_manager.py ([`278f05f`](https://github.com/tekgnosis-net/BunkrDownloader/commit/278f05f34cc3a3c46b06dcafe5217a7a33b7d4a4))

* Update README.md ([`92f59f2`](https://github.com/tekgnosis-net/BunkrDownloader/commit/92f59f23277104fa68423b826f4a780ed6ccb27a))

* Update README.md ([`709a565`](https://github.com/tekgnosis-net/BunkrDownloader/commit/709a5650b11a9bba8fe9a9de20214131185bb671))

* Update README.md ([`936d8bc`](https://github.com/tekgnosis-net/BunkrDownloader/commit/936d8bca9503e0e3117f6deb38069c7515ca48a2))

* Update README.md ([`1caf7b1`](https://github.com/tekgnosis-net/BunkrDownloader/commit/1caf7b1c21c77453834e1a4d16d76dd5e8bcac42))

* Update progress_manager.py ([`a49575a`](https://github.com/tekgnosis-net/BunkrDownloader/commit/a49575ac7325b6e695f6183822a3bd866a3489eb))

* Update live_manager.py ([`cd93c21`](https://github.com/tekgnosis-net/BunkrDownloader/commit/cd93c21fe2562e5e77d9d58a996891ec05db8903))

* Update downloader.py ([`4ad4387`](https://github.com/tekgnosis-net/BunkrDownloader/commit/4ad43879d85f3893aa9b19e00a1d3f5994621457))

* Update README.md ([`a45ce3d`](https://github.com/tekgnosis-net/BunkrDownloader/commit/a45ce3da79eff5399965af17b23ae6a0dbe1d88c))

* Improved directory structure

Improved directory structure for better logical grouping by adding a &#39;crawlers&#39; subdirectory. ([`b2364a2`](https://github.com/tekgnosis-net/BunkrDownloader/commit/b2364a21a1555ce0dc5afd188a534bd4e956c013))

* Delete helpers directory ([`0d2e49b`](https://github.com/tekgnosis-net/BunkrDownloader/commit/0d2e49b7d94570051a7a5e94b681a8a8d9726c35))

* Update main.py

Refactored the code according to the new helpers directory structure. ([`1c918d8`](https://github.com/tekgnosis-net/BunkrDownloader/commit/1c918d839e80d5b2dc4f8d3ed222bcef7166dc6a))

* Update downloader.py

Refactored the code according to the new helpers directory structure. ([`4f159ea`](https://github.com/tekgnosis-net/BunkrDownloader/commit/4f159ea2516599307185d9604c41bea21c033674))

* Update README.md ([`01e7986`](https://github.com/tekgnosis-net/BunkrDownloader/commit/01e7986d80c9b8bec50ba0d8946b5b43b56af054))

* Update README.md ([`8a95bea`](https://github.com/tekgnosis-net/BunkrDownloader/commit/8a95bea1e1182c8cd90071f68a2d8ace4322a364))

* Add files via upload ([`3bc786d`](https://github.com/tekgnosis-net/BunkrDownloader/commit/3bc786d91f2950fbc1df120b7ebbb6ff90e4e6fd))

* Delete misc/Demo.gif ([`6f5d166`](https://github.com/tekgnosis-net/BunkrDownloader/commit/6f5d166fca19a3695d89207ad1ab254a0a5548a9))

* Update downloader.py ([`04bfefe`](https://github.com/tekgnosis-net/BunkrDownloader/commit/04bfefe58a3f011875e0368c170302f357ccda9a))

* Update README.md ([`cff2ab3`](https://github.com/tekgnosis-net/BunkrDownloader/commit/cff2ab30f27402c57ebda99109882db5452a1e3e))

* Update README.md ([`87fc872`](https://github.com/tekgnosis-net/BunkrDownloader/commit/87fc8723a69db60dfc09e848f35fd708121d8b34))

* Delete helpers/managers/__pycache__ directory ([`6cd745d`](https://github.com/tekgnosis-net/BunkrDownloader/commit/6cd745d60e27d87a905da7d37e877a932568be55))

* Delete helpers/__pycache__ directory ([`3274406`](https://github.com/tekgnosis-net/BunkrDownloader/commit/32744062ad54d996a006112f148b12429b295460))

* Update README.md ([`543fe8c`](https://github.com/tekgnosis-net/BunkrDownloader/commit/543fe8c7570fc89a3abde2fc423ab0501adad0e9))

* Update README.md ([`79c9e86`](https://github.com/tekgnosis-net/BunkrDownloader/commit/79c9e865ed1dc7f671c7221cc6f7cf9de1206495))

* Update README.md ([`e324498`](https://github.com/tekgnosis-net/BunkrDownloader/commit/e324498fcb11422f8e01896efc97fbed9d36314b))

* Update README.md ([`a8cb411`](https://github.com/tekgnosis-net/BunkrDownloader/commit/a8cb41165639185ef2e9d95589363b9edd78ef3c))

* Updated helper functions

Update helpers to implement live manager and log manager for real-time logging; improve directory structure for better modularization

- Added live manager and log manager in helpers to enable real-time log tracking.
- Enhanced the directory structure for improved modularization and organization.
- Refactored related code for better maintainability and scalability. ([`70383e6`](https://github.com/tekgnosis-net/BunkrDownloader/commit/70383e6cfc4b9bae0c65c2283d0b733dc453992e))

* Delete helpers directory ([`5b0b9e7`](https://github.com/tekgnosis-net/BunkrDownloader/commit/5b0b9e709e7f78878c4cb4e545ec6f2f15819839))

* Updated downloader.py

Refactor code to support multiple async downloads, live log table, and improve readability.

- Refactored the download logic to handle multiple async downloads concurrently.
- Integrated a live log table to track download progress in real time.
- Improved code structure and organization for better readability and maintainability.
- Updated function names and added comments for clarity. ([`5b57be6`](https://github.com/tekgnosis-net/BunkrDownloader/commit/5b57be64fa78b52546644b1ed41509c13a878240))

* Updated main scripts

Updated main scripts to reflect the modularization of helper functions and the changes in downloader. ([`2d8991f`](https://github.com/tekgnosis-net/BunkrDownloader/commit/2d8991f646ff66dd3de84d0a2b66b54e27c39eff))

* Update playwright_downloader.py ([`dcb4461`](https://github.com/tekgnosis-net/BunkrDownloader/commit/dcb44616ac66908f3df5a660f4378046805eed5d))

* Update downloader.py ([`d1f5302`](https://github.com/tekgnosis-net/BunkrDownloader/commit/d1f53027f0e36a6a63342e1f77c9b404e2f78781))

* Updated main scripts

Updated main scripts to reflect the modularization of helpers ([`a8c4ba3`](https://github.com/tekgnosis-net/BunkrDownloader/commit/a8c4ba3b1bfb6ddde79ea9171c3ef5eda45dc64a))

* Refactored helper functions to enhance modularity ([`dcba07c`](https://github.com/tekgnosis-net/BunkrDownloader/commit/dcba07c3419dbbfc9365a65dfba3b383f188785e))

* Update README.md ([`833bfec`](https://github.com/tekgnosis-net/BunkrDownloader/commit/833bfec437fcccfb5f9725c4df05496def544d50))

* Refactored helper functions to enhance modularity ([`0639613`](https://github.com/tekgnosis-net/BunkrDownloader/commit/0639613268ac8308f608fb387d6bd53cfa1e60bf))

* Add files via upload ([`a6f9cc9`](https://github.com/tekgnosis-net/BunkrDownloader/commit/a6f9cc995ea348c1c77e3c0799acd92e438231fc))

* Update README.md ([`b9357ea`](https://github.com/tekgnosis-net/BunkrDownloader/commit/b9357eadaf714830df2e354c36ab5131b5421d5e))

* Update README.md ([`34b9277`](https://github.com/tekgnosis-net/BunkrDownloader/commit/34b927730e8a7aca87bb5dbf7a0e4fca51611ee6))

* Add files via upload ([`fc822fa`](https://github.com/tekgnosis-net/BunkrDownloader/commit/fc822fa8bdee0cff534ba83dfcc6106357ebb84a))

* Add files via upload ([`aacee5f`](https://github.com/tekgnosis-net/BunkrDownloader/commit/aacee5fefdaa83f84ec7f7d8f8648efd492f4247))

* Add files via upload ([`99a512e`](https://github.com/tekgnosis-net/BunkrDownloader/commit/99a512ec94476af6605e5a925995fd0d2a25c4b7))

* Add files via upload ([`0a15d32`](https://github.com/tekgnosis-net/BunkrDownloader/commit/0a15d32b62a25922cb7a4aa4c374b447967a58ad))

* Update download_utils.py ([`af8eba7`](https://github.com/tekgnosis-net/BunkrDownloader/commit/af8eba70507d73d866f60b8022dc6b535f1e15bf))

* Add files via upload ([`42261f4`](https://github.com/tekgnosis-net/BunkrDownloader/commit/42261f42e1e80c8a76db0b57d14bd215b8899446))

* Add files via upload ([`5dccafc`](https://github.com/tekgnosis-net/BunkrDownloader/commit/5dccafc3c7eb179b0a8fcee3edb8de2412dd3121))

* Update download_utils.py ([`e59e5f1`](https://github.com/tekgnosis-net/BunkrDownloader/commit/e59e5f17043cb5b57aa58ff10dc7549b51c815aa))

* Update downloader.py ([`2b3f9bd`](https://github.com/tekgnosis-net/BunkrDownloader/commit/2b3f9bde1d80cd9bb536964443cf1a3c8e9386c5))

* Update download_utils.py ([`6d4fded`](https://github.com/tekgnosis-net/BunkrDownloader/commit/6d4fded7db1434d59ed53c2d35aec72854ee5b82))

* Add files via upload ([`17d1d7e`](https://github.com/tekgnosis-net/BunkrDownloader/commit/17d1d7ec9a607d918c5fd93e44d67955c4840281))

* Update main.py ([`8b01349`](https://github.com/tekgnosis-net/BunkrDownloader/commit/8b01349f7b808879010fad6361d59d6e53f4fe4b))

* Update downloader.py ([`6307517`](https://github.com/tekgnosis-net/BunkrDownloader/commit/63075172027150c54b021646fb359febddef2b7f))

* Update README.md ([`e8f682b`](https://github.com/tekgnosis-net/BunkrDownloader/commit/e8f682b8066c4cac9ad35d2e7b9617e76d205720))

* Update README.md ([`e58e880`](https://github.com/tekgnosis-net/BunkrDownloader/commit/e58e88094f2330ac53916d80fe5af47bea881c63))

* Add files via upload ([`bb78775`](https://github.com/tekgnosis-net/BunkrDownloader/commit/bb78775e6d94c035ba80f9520ae21251dba69d1b))

* Delete helpers/__pycache__ directory ([`45149ee`](https://github.com/tekgnosis-net/BunkrDownloader/commit/45149ee18a417343b081f838653e06d2f65451da))

* Update main.py ([`3101cbd`](https://github.com/tekgnosis-net/BunkrDownloader/commit/3101cbd0ee8d5ef592cde7ec8c6b9fa4356cfa5f))

* Update downloader.py ([`81a0944`](https://github.com/tekgnosis-net/BunkrDownloader/commit/81a0944e02d5ebf2c9b4a10e33c76ed5dede5e56))

* Update requirements.txt ([`6e197a2`](https://github.com/tekgnosis-net/BunkrDownloader/commit/6e197a2554828ad8a1bc1a54bf414d079cb9bcc3))

* Update README.md ([`8050a68`](https://github.com/tekgnosis-net/BunkrDownloader/commit/8050a68e759d6fd77f5a77b58f6c9807973065a0))

* Update README.md ([`4cb030f`](https://github.com/tekgnosis-net/BunkrDownloader/commit/4cb030fce0a4294a3eb3f0333776d798d52393be))

* Add files via upload ([`0d59088`](https://github.com/tekgnosis-net/BunkrDownloader/commit/0d5908806df7d691e2ce8a4735dec4c968a0e75b))

* Update bunkr_utils.py ([`2f12d26`](https://github.com/tekgnosis-net/BunkrDownloader/commit/2f12d263d66ea6e42dc187d2fb20dcc61d03100d))

* Update progress_utils.py ([`8ee8360`](https://github.com/tekgnosis-net/BunkrDownloader/commit/8ee8360fdb7360b9d0745267bc80873b882a7e62))

* Update downloader.py ([`81a04fc`](https://github.com/tekgnosis-net/BunkrDownloader/commit/81a04fc10f683f4b26b18f104b263c6aa3973470))

* Update main.py ([`94a85f4`](https://github.com/tekgnosis-net/BunkrDownloader/commit/94a85f4c037f40a9988ad9bde99eef025b6729dd))

* Update downloader.py ([`38de3a9`](https://github.com/tekgnosis-net/BunkrDownloader/commit/38de3a936fb63859dab7a1dab9f1450068561e3e))

* Update main.py ([`2a4d3b0`](https://github.com/tekgnosis-net/BunkrDownloader/commit/2a4d3b0b60bfd628c54d6e8c4aaca69538fe331f))

* Update playwright_downloader.py ([`b5997ad`](https://github.com/tekgnosis-net/BunkrDownloader/commit/b5997add0084245247b5ee4110e6f29b358a8706))

* Add files via upload ([`5228977`](https://github.com/tekgnosis-net/BunkrDownloader/commit/5228977258764c98645d0107da59e2c2fe604f53))

* Update playwright_downloader.py ([`fba9c67`](https://github.com/tekgnosis-net/BunkrDownloader/commit/fba9c67a5b9ef21cddccd21895513d3a4a3ded44))

* Update bunkr_utils.py ([`531a9b6`](https://github.com/tekgnosis-net/BunkrDownloader/commit/531a9b67f555f53027679021e637f0d1917abf43))

* Update README.md ([`f7407d0`](https://github.com/tekgnosis-net/BunkrDownloader/commit/f7407d0bd4a7abdd8d389d0548f50c03488ec1c4))

* Add files via upload ([`b334cf2`](https://github.com/tekgnosis-net/BunkrDownloader/commit/b334cf27fff8ca734b942e32186338592405a45f))

* Delete misc/ScreenshotBunkr.png ([`5c312f2`](https://github.com/tekgnosis-net/BunkrDownloader/commit/5c312f29807dcdab096dd02bec1197cf05cb0300))

* Update README.md ([`1070e79`](https://github.com/tekgnosis-net/BunkrDownloader/commit/1070e797adcec5c10f3a5d1a3e3b9a60c10962b5))

* Update playwright_downloader.py ([`d27319f`](https://github.com/tekgnosis-net/BunkrDownloader/commit/d27319f772de9380e1138db404c3b903936b02ad))

* Add files via upload ([`3c02837`](https://github.com/tekgnosis-net/BunkrDownloader/commit/3c02837ce5e6487ac5e2636ebcd2a97bbc769da9))

* Delete helpers/bunkr_status.py ([`f9ef5e9`](https://github.com/tekgnosis-net/BunkrDownloader/commit/f9ef5e9d9bd0634cccd9a1a6d7eda62d853b0959))

* Update bunkr_status.py ([`2785153`](https://github.com/tekgnosis-net/BunkrDownloader/commit/2785153c67dd23e08f0939761e26113da5c72bf8))

* Update downloader.py ([`9fc8181`](https://github.com/tekgnosis-net/BunkrDownloader/commit/9fc8181a01b78c1af9a4a43563390ea976daf7b5))

* Update downloader.py ([`369aedd`](https://github.com/tekgnosis-net/BunkrDownloader/commit/369aedd3d2b010b7b74896a5a71237be534bb276))

* Update main.py ([`40c6c7b`](https://github.com/tekgnosis-net/BunkrDownloader/commit/40c6c7bb8048635cd9349131035add49e7801b1f))

* Update bunkr_status.py ([`7157dc5`](https://github.com/tekgnosis-net/BunkrDownloader/commit/7157dc521d0f562a21817fae9015b712a979c7bf))

* Update README.md ([`25a5ed1`](https://github.com/tekgnosis-net/BunkrDownloader/commit/25a5ed1e7b3d65770271b41bddb82b5bdce9a33a))

* Update playwright_downloader.py ([`adc1d3b`](https://github.com/tekgnosis-net/BunkrDownloader/commit/adc1d3bda6e36e944c18eaa272a414428d4146e8))

* Update playwright_downloader.py ([`b6f6a6a`](https://github.com/tekgnosis-net/BunkrDownloader/commit/b6f6a6a619de6e835679e7b86b9ea2f849a8071f))

* Update playwright_downloader.py ([`12c18de`](https://github.com/tekgnosis-net/BunkrDownloader/commit/12c18de5db80bbc0541ed3db5ca9abf952ea7a66))

* Add files via upload

Module to fetch the  operational status of servers from the Bunkr status page. ([`fee0235`](https://github.com/tekgnosis-net/BunkrDownloader/commit/fee0235e0086f4019ff8bcba018d8113138170ff))

* Update downloader.py

Added a check for subdomain status to skip non-operational download links. ([`364d444`](https://github.com/tekgnosis-net/BunkrDownloader/commit/364d444f93edc3c30ad21b160cf4632748681948))

* Update README.md ([`33ea945`](https://github.com/tekgnosis-net/BunkrDownloader/commit/33ea945aab9584bf9239c39428f16b8f5cc4ba45))

* Add files via upload ([`9616448`](https://github.com/tekgnosis-net/BunkrDownloader/commit/9616448de4b4c90204535c602e99273029c0d800))

* Delete misc/Screenshot.png ([`6426ee0`](https://github.com/tekgnosis-net/BunkrDownloader/commit/6426ee00c81ee4c8fd437c30e2de0cdaab9f267f))

* Add files via upload ([`ddd8af5`](https://github.com/tekgnosis-net/BunkrDownloader/commit/ddd8af54c5724918fc81224e3fa2cb70eccbe6b5))

* Delete misc/Screenshot.png ([`56b80ed`](https://github.com/tekgnosis-net/BunkrDownloader/commit/56b80edae69a773cb1842f96c4964b0fd1dc0bb7))

* Add files via upload ([`7656d12`](https://github.com/tekgnosis-net/BunkrDownloader/commit/7656d12ec51c3002986333db1b138feb70c95dd2))

* Delete misc/ScreenshotBunkr.png ([`c13cd9e`](https://github.com/tekgnosis-net/BunkrDownloader/commit/c13cd9ea9587f8789326c5f88cd533a2765733cf))

* Update README.md ([`791d330`](https://github.com/tekgnosis-net/BunkrDownloader/commit/791d330fdb156833b08d81c19e2a7d866f4e1b6d))

* Add files via upload ([`204f721`](https://github.com/tekgnosis-net/BunkrDownloader/commit/204f721ee9b9b68b78f9e4b2adf2052a44ae5a69))

* Delete misc/Screenshot.png ([`567b2f1`](https://github.com/tekgnosis-net/BunkrDownloader/commit/567b2f14745f815b7a2d0e76f500e6fd7e7d6ac8))

* Add files via upload ([`715a226`](https://github.com/tekgnosis-net/BunkrDownloader/commit/715a2268eec0b489a6aeaed34f721c5e4137c3c5))

* Delete misc/Screenshot.png ([`bfdcbc8`](https://github.com/tekgnosis-net/BunkrDownloader/commit/bfdcbc81ebe7796ad18ff7199ceb1c141ea94694))

* Add files via upload ([`0f9c91c`](https://github.com/tekgnosis-net/BunkrDownloader/commit/0f9c91c4010fb0ba44bf9ba3952c1cc059e08981))

* Update downloader.py ([`6e539e5`](https://github.com/tekgnosis-net/BunkrDownloader/commit/6e539e52fa626da475f01b68e96459d71028a0c5))

* Update README.md ([`b24e022`](https://github.com/tekgnosis-net/BunkrDownloader/commit/b24e0222c5c9aeee47883ed43c7d861c795df70a))

* Update .gitignore ([`657cbfa`](https://github.com/tekgnosis-net/BunkrDownloader/commit/657cbfa21d85b726fbb1fe6be58df6e6727280fa))

* Update playwright_downloader.py ([`3735deb`](https://github.com/tekgnosis-net/BunkrDownloader/commit/3735deb34d3bc031cf1bc43eee3dd404d5b2c9ca))

* Update requirements.txt ([`c29b429`](https://github.com/tekgnosis-net/BunkrDownloader/commit/c29b42911bfce91f50c102f392190aeb4f0f71bc))

* Update README.md ([`7c8f161`](https://github.com/tekgnosis-net/BunkrDownloader/commit/7c8f161bba0cd30af8a6a48920e85108e5ef8c43))

* Update requirements.txt ([`4029bb9`](https://github.com/tekgnosis-net/BunkrDownloader/commit/4029bb9cd0ecaaae52e5d93071e39591d524d532))

* Update README.md ([`d06bcae`](https://github.com/tekgnosis-net/BunkrDownloader/commit/d06bcae3d238d952066c11cf8ed855441a9cef37))

* Update README.md ([`68c3c5c`](https://github.com/tekgnosis-net/BunkrDownloader/commit/68c3c5c8540a05bef14089726ffb28b35283dfc3))

* Update README.md ([`81d567b`](https://github.com/tekgnosis-net/BunkrDownloader/commit/81d567befc0a5524fe73be5bbde624d26622ff4a))

* Update main.py ([`6bd4463`](https://github.com/tekgnosis-net/BunkrDownloader/commit/6bd4463e136d064c7a8ae3ea49ecd4873c08e5a0))

* Add files via upload ([`38baf2f`](https://github.com/tekgnosis-net/BunkrDownloader/commit/38baf2f32e803c864d053185e7cf29861df27400))

* Delete helpers/downloader.py ([`3804739`](https://github.com/tekgnosis-net/BunkrDownloader/commit/38047390424d9d970c222bbf65649e0a19c72272))

* Update downloader.py ([`16b4bab`](https://github.com/tekgnosis-net/BunkrDownloader/commit/16b4baba9b436cacc1aec7874fa60d27ca49c3a4))

* Delete downloader.py ([`bf294f5`](https://github.com/tekgnosis-net/BunkrDownloader/commit/bf294f5f332fa9abfdfd4aa83ccbcbc32965176e))

* Update README.md ([`2520acb`](https://github.com/tekgnosis-net/BunkrDownloader/commit/2520acb07eaa2b5938f93e0b9b914d0b7f8be926))

* Update README.md ([`1b1fa7a`](https://github.com/tekgnosis-net/BunkrDownloader/commit/1b1fa7a9eb5f0630cb96cd92a4a8d83b93e63d67))

* Update playwright_downloader.py ([`63331ec`](https://github.com/tekgnosis-net/BunkrDownloader/commit/63331ec4616e53da846051eaddbf427332b43206))

* Update downloader.py ([`0afb506`](https://github.com/tekgnosis-net/BunkrDownloader/commit/0afb5067e4a392a66f836f71eb5f29860f961967))

* Update README.md ([`0b4dfbf`](https://github.com/tekgnosis-net/BunkrDownloader/commit/0b4dfbf613e8686535b40bdfbcaef83f492765e6))

* Add files via upload ([`32413d8`](https://github.com/tekgnosis-net/BunkrDownloader/commit/32413d861de1b1acc7a0d2a59fedefa04c59142b))

* Delete start.sh ([`efbbef8`](https://github.com/tekgnosis-net/BunkrDownloader/commit/efbbef8ae7d7dc451fde666b09d69c33069a2a1b))

* Delete utils directory ([`59fb02d`](https://github.com/tekgnosis-net/BunkrDownloader/commit/59fb02d2920eda240b28afd6a9f8e877a77c47c3))

* Update downloader.py ([`dd1568e`](https://github.com/tekgnosis-net/BunkrDownloader/commit/dd1568e2142a4630c562d8409905b6250412708a))

* Update downloader.py ([`946950c`](https://github.com/tekgnosis-net/BunkrDownloader/commit/946950cca43ef8e09bc8017a709760d6d9f6252e))

* Update playwright_downloader.py ([`6a5754f`](https://github.com/tekgnosis-net/BunkrDownloader/commit/6a5754ffa37183d47af6b754fa790de7688ade80))

* Update downloader.py ([`8d1b451`](https://github.com/tekgnosis-net/BunkrDownloader/commit/8d1b4511c271b9ad4b37156dd3051f60057dcc87))

* Update downloader.py ([`6d56961`](https://github.com/tekgnosis-net/BunkrDownloader/commit/6d56961d7b4898b97d4abef366600f7da4269af2))

* Update playwright_downloader.py ([`9cc9af9`](https://github.com/tekgnosis-net/BunkrDownloader/commit/9cc9af97135b1b023713c854dffe733d9b01d203))

* Update downloader.py ([`6190469`](https://github.com/tekgnosis-net/BunkrDownloader/commit/61904694669202bbd4b523e6bb988b204071c513))

* Update downloader.py ([`b874075`](https://github.com/tekgnosis-net/BunkrDownloader/commit/b874075d8619f60a893eae4b815d686c3f783157))

* Update README.md ([`87d2416`](https://github.com/tekgnosis-net/BunkrDownloader/commit/87d24165febc873cbf966b60b9d42c79d8c0d92f))

* Update README.md ([`3a3283e`](https://github.com/tekgnosis-net/BunkrDownloader/commit/3a3283e27ffe2cc398b270009f017eccd891326a))

* Update LICENSE ([`f91b6d2`](https://github.com/tekgnosis-net/BunkrDownloader/commit/f91b6d2e5bccf5a56c5263753d0954296475e991))

* Update downloader.py ([`6e135e1`](https://github.com/tekgnosis-net/BunkrDownloader/commit/6e135e10271d316f6d573ac9811b4ed54fa4a997))

* Update start.sh ([`ec59880`](https://github.com/tekgnosis-net/BunkrDownloader/commit/ec598808c7cc8ee0c102d32d792083f31703bd03))

* Update README.md ([`ea718c1`](https://github.com/tekgnosis-net/BunkrDownloader/commit/ea718c109d61eaf5388e0efed6cbfec8acaab0b1))

* Update README.md ([`3ecc193`](https://github.com/tekgnosis-net/BunkrDownloader/commit/3ecc193849b67f278d66cde50524c17de1031843))

* Update README.md ([`914c43f`](https://github.com/tekgnosis-net/BunkrDownloader/commit/914c43f0354b27a6161ad95c0aaffbb106f10513))

* Update README.md ([`eab1822`](https://github.com/tekgnosis-net/BunkrDownloader/commit/eab1822f07ac9929cc5a34aac5599ccf323d90b2))

* Update README.md ([`1edfc47`](https://github.com/tekgnosis-net/BunkrDownloader/commit/1edfc47640d1e8f1a92fa1bbf2280e9131c0b51e))

* Update README.md ([`9d73e87`](https://github.com/tekgnosis-net/BunkrDownloader/commit/9d73e87e22162e85e443a8962b594c4c38c5e6c7))

* Add files via upload ([`b576d12`](https://github.com/tekgnosis-net/BunkrDownloader/commit/b576d121afd38207e9e70e5d48572e17b1064b74))

* Add files via upload ([`c7259d0`](https://github.com/tekgnosis-net/BunkrDownloader/commit/c7259d01655314795258bfac679010aa1dfc25ff))

* Create .gitignore ([`227dbad`](https://github.com/tekgnosis-net/BunkrDownloader/commit/227dbadb6b30c9773c2611d8c91e89fa9a718cc0))

* Create requirements.txt ([`0af4b52`](https://github.com/tekgnosis-net/BunkrDownloader/commit/0af4b5272c99b24290af6f7f0ef49cbb4798057d))

* Create README.md ([`3adc61e`](https://github.com/tekgnosis-net/BunkrDownloader/commit/3adc61ed61881cfe2174e91d17749dbf0fb24f79))

## v0.0.0 (2025-11-17)

### Unknown

* Main entry point of the script ([`f9edf28`](https://github.com/tekgnosis-net/BunkrDownloader/commit/f9edf283a49815d0b724de12e4a37e888e86419f))
