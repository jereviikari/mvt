# Mobile Verification Toolkit (MVT)
# Copyright (c) 2021 The MVT Project Authors.
# Use of this software is governed by the MVT License 1.1 that can be found at
#   https://license.mvt.re/1.1/

import sqlite3

from mvt.common.url import URL
from mvt.common.utils import convert_mactime_to_unix, convert_timestamp_to_iso

from ..base import IOSExtraction

SAFARI_HISTORY_BACKUP_IDS = [
    "e74113c185fd8297e140cfcf9c99436c5cc06b57",
    "1a0e7afc19d307da602ccdcece51af33afe92c53",
]
SAFARI_HISTORY_ROOT_PATHS = [
    "private/var/mobile/Library/Safari/History.db",
    "private/var/mobile/Containers/Data/Application/*/Library/Safari/History.db",
]

class SafariHistory(IOSExtraction):
    """This module extracts all Safari visits and tries to detect potential
    network injection attacks."""

    def __init__(self, file_path=None, base_folder=None, output_folder=None,
                 fast_mode=False, log=None, results=[]):
        super().__init__(file_path=file_path, base_folder=base_folder,
                         output_folder=output_folder, fast_mode=fast_mode,
                         log=log, results=results)

    def serialize(self, record):
        return {
            "timestamp": record["isodate"],
            "module": self.__class__.__name__,
            "event": "safari_history",
            "data": f"Safari visit to {record['url']} (ID: {record['id']}, Visit ID: {record['visit_id']})",
        }

    def _find_injections(self):
        for result in self.results:
            # We presume injections only happen on HTTP visits.
            if not result["url"].lower().startswith("http://"):
                continue

            # If there is no destination, no redirect happened.
            if not result["redirect_destination"]:
                continue

            origin_domain = URL(result["url"]).domain

            # We loop again through visits in order to find redirect record.
            for redirect in self.results:
                if redirect["visit_id"] != result["redirect_destination"]:
                    continue

                redirect_domain = URL(redirect["url"]).domain
                # If the redirect destination is the same domain as the origin,
                # it's most likely an HTTPS upgrade.
                if origin_domain == redirect_domain:
                    continue

                self.log.info("Found HTTP redirect to different domain: \"%s\" -> \"%s\"",
                         origin_domain, redirect_domain)

                redirect_time = convert_mactime_to_unix(redirect["timestamp"])
                origin_time = convert_mactime_to_unix(result["timestamp"])
                elapsed_time = redirect_time - origin_time
                elapsed_ms = elapsed_time.microseconds / 1000

                if elapsed_time.seconds == 0:
                    self.log.warning("Redirect took less than a second! (%d milliseconds)", elapsed_ms)

    def check_indicators(self):
        self._find_injections()

        if not self.indicators:
            return

        for result in self.results:
            if self.indicators.check_domain(result["url"]):
                self.detected.append(result)

    def run(self):
        self._find_ios_database(backup_ids=SAFARI_HISTORY_BACKUP_IDS, root_paths=SAFARI_HISTORY_ROOT_PATHS)
        self.log.info("Found Safari history database at path: %s", self.file_path)

        conn = sqlite3.connect(self.file_path)
        cur = conn.cursor()
        cur.execute("""
            SELECT
                history_items.id,
                history_items.url,
                history_visits.id,
                history_visits.visit_time,
                history_visits.redirect_source,
                history_visits.redirect_destination
            FROM history_items
            JOIN history_visits ON history_visits.history_item = history_items.id
            ORDER BY history_visits.visit_time;
        """)

        items = []
        for item in cur:
            items.append({
                "id": item[0],
                "url": item[1],
                "visit_id": item[2],
                "timestamp": item[3],
                "isodate": convert_timestamp_to_iso(convert_mactime_to_unix(item[3])),
                "redirect_source": item[4],
                "redirect_destination": item[5]
            })

        cur.close()
        conn.close()

        self.log.info("Extracted a total of %d history items", len(items))
        self.results = items
