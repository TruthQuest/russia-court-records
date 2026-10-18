# Source and license

`sudrf_websites.json` and `rf_region_codes.json` are from the sudrfparser project by Dataout
(https://github.com/dataout-org/sudrfparser, folder `courts_info`), scraped from the official
portal https://sudrf.ru/index.php?id=300 on 18 November 2023.

Licensed under Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0),
https://creativecommons.org/licenses/by-sa/4.0/ . Derived court lists (work/courts.csv) carry the
same license. Credit Dataout in any publication that uses the court list.

The list predates some host and court changes; courts that no longer respond are logged by
03_search.py (search_log.csv, status -1 or 404).
