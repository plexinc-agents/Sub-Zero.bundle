# coding=utf-8
import traceback

import re

from support.config import config
from support.helpers import format_item, query_plex, format_video
from ignore import ignore_list
from lib import Plex


def itemDiscoverMissing(rating_key, kind="show", added_at=None, section_title=None, internal=False, external=True, languages=()):
    existing_subs = {"internal": [], "external": [], "count": 0}

    item_id = int(rating_key)
    item_container = Plex["library"].metadata(item_id)

    item = list(item_container)[0]

    if kind == "show":
        item_title = format_item(item, kind, parent=item.season, section_title=section_title, parent_title=item.show.title)
    else:
        item_title = format_item(item, kind, section_title=section_title)

    video = item.media

    for part in video.parts:
        for stream in part.streams:
            if stream.stream_type == 3:
                if stream.index:
                    key = "internal"
                else:
                    key = "external"

                existing_subs[key].append(Locale.Language.Match(stream.language_code or ""))
                existing_subs["count"] = existing_subs["count"] + 1

    missing = languages
    if existing_subs["count"]:
        existing_flat = (existing_subs["internal"] if internal else []) + (existing_subs["external"] if external else [])
        languages_set = set(languages)
        if languages_set.issubset(existing_flat):
            # all subs found
            Log.Info(u"All subtitles exist for '%s'", item_title)
            return

        missing = languages_set - set(existing_flat)
        Log.Info(u"Subs still missing for '%s': %s", item_title, missing)

    if missing:
        return added_at, item_id, item_title


def getRecentMissing(items):
    missing = []
    for added_at, kind, section_title, key in items:
        try:
            state = itemDiscoverMissing(
                key,
                kind=kind,
                added_at=added_at,
                section_title=section_title,
                languages=config.langList,
                internal=bool(Prefs["subtitles.scan.embedded"]),
                external=bool(Prefs["subtitles.scan.external"])
            )
            if state:
                # (added_at, item_id, title)
                missing.append(state)
        except:
            Log.Error("Something went wrong when getting the state of item %s: %s", key, traceback.format_exc())
    return missing


storage_type_re = re.compile(ur'(<Video.*?type="(\w+)"[^>]+>.*?</Video>)', re.DOTALL)
storage_episode_re = re.compile(ur'ratingKey="(?P<key>\d+)"'
                                ur'.+?grandparentRatingKey="(?P<parent_key>\d+)"'
                                ur'.+?title="(?P<title>.*?)"'
                                ur'.+?grandparentTitle="(?P<parent_title>.*?)"'
                                ur'.+?index="(?P<episode>\d+?)"'
                                ur'.+?parentIndex="(?P<season>\d+?)".+?addedAt="(?P<added>\d+)"')

storage_movie_re = re.compile(ur'ratingKey="(?P<key>\d+)".+?title="(?P<title>.*?)".+?addedAt="(?P<added>\d+)"')
available_keys = ("type", "key", "title", "parent_key", "parent_title", "season", "episode", "added")


def getMissingItems():
    wanted_languages = set(config.langList)
    missing_subs = []
    for item_id, parts in Dict["subs"].iteritems():
        missing = []
        for part_id, languages in parts.iteritems():
            language_list = languages.keys()

            if not languages:
                missing = config.langList
            else:
                parsed_languages = [Locale.Language.Match(code) for code in language_list]
                missing = wanted_languages.difference(parsed_languages)
        if missing:
            missing_subs.append(item_id)

    if not missing_subs:
        return

    args = {
        "X-Plex-Container-Start": "0",
        "X-Plex-Container-Size": "200"
    }
    url = "https://127.0.0.1:32400/library/metadata/%s" % ",".join(missing_subs)
    response = query_plex(url, args)

    by_type = storage_type_re.findall(response.content)

    items = []
    if by_type:
        for video, kind in by_type:
            matcher = storage_episode_re if kind == "episode" else storage_movie_re
            matches = [m.groupdict() for m in matcher.finditer(video)]
            for match in matches:
                data = dict((key, match[key] if key in match else None) for key in available_keys)
                if kind == "episode":
                    if data["parent_key"] in ignore_list.series or data["key"] in ignore_list.videos:
                        continue

                    item_title = format_video("show", data["title"], section_title="Episode", parent_title=data["parent_title"],
                                              season=int(data["season"] or 0), episode=int(data["episode"] or 0), add_section_title=True)
                else:
                    if data["key"] in ignore_list.videos:
                        continue

                    item_title = format_video("movie", data["title"], section_title="Movie", add_section_title=True)
                items.append((unicode(item_title), data["key"]))
        items.sort()
    return items


def refresh_item(item, title):
    Plex["library/metadata"].refresh(item)


def refresh_items(items):
    for item, title in items:
        refresh_item(item, title)
