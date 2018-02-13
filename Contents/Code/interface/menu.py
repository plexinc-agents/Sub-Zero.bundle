# coding=utf-8
import locale
import logging
import os
import platform
import traceback

import logger
import copy

from requests import HTTPError
from item_details import ItemDetailsMenu
from refresh_item import RefreshItem
from menu_helpers import add_ignore_options, dig_tree, set_refresh_menu_state, \
    default_thumb, debounce, ObjectContainer, SubFolderObjectContainer, route, \
    extract_embedded_sub
from main import fatality, IgnoreMenu
from advanced import DispatchRestart
from subzero.constants import ART, PREFIX, DEPENDENCY_MODULE_NAMES
from support.plex_media import get_all_parts, get_embedded_subtitle_streams
from support.scheduler import scheduler
from support.config import config
from support.helpers import timestamp, df, display_language
from support.ignore import ignore_list
from support.items import get_all_items, get_items_info, get_item_kind_from_rating_key, get_item, MI_KEY, get_item_title
from support.storage import get_subtitle_storage

# init GUI
ObjectContainer.art = R(ART)
ObjectContainer.no_cache = True

# default thumb for DirectoryObjects
DirectoryObject.thumb = default_thumb
Plugin.AddViewGroup("full_details", viewMode="InfoList", mediaType="items", type="list", summary=2)


@route(PREFIX + '/section/firstLetter/key', deeper=bool)
def FirstLetterMetadataMenu(rating_key, key, title=None, base_title=None, display_items=False, previous_item_type=None,
                            previous_rating_key=None):
    """
    displays the contents of a section filtered by the first letter
    :param rating_key: actually is the section's key
    :param key: the firstLetter wanted
    :param title: the first letter, or #
    :param deeper:
    :return:
    """
    title = base_title + " > " + unicode(title)
    oc = SubFolderObjectContainer(title2=title, no_cache=True, no_history=True)

    items = get_all_items(key="first_character", value=[rating_key, key], base="library/sections", flat=False)
    kind, deeper = get_items_info(items)
    dig_tree(oc, items, MetadataMenu,
             pass_kwargs={"base_title": title, "display_items": deeper, "previous_item_type": kind,
                          "previous_rating_key": rating_key})
    return oc


@route(PREFIX + '/section/contents', display_items=bool)
def MetadataMenu(rating_key, title=None, base_title=None, display_items=False, previous_item_type=None,
                 previous_rating_key=None, header=None, randomize=None):
    """
    displays the contents of a section based on whether it has a deeper tree or not (movies->movie (item) list; series->series list)
    :param rating_key:
    :param title:
    :param base_title:
    :param display_items:
    :param previous_item_type:
    :param previous_rating_key:
    :return:
    """
    title = unicode(title)
    item_title = title
    title = base_title + " > " + title
    oc = SubFolderObjectContainer(title2=title, no_cache=True, no_history=True, header=header,
                                  view_group="full_details")

    current_kind = get_item_kind_from_rating_key(rating_key)

    if display_items:
        timeout = 30
        show = None

        # add back to series for season
        if current_kind == "season":
            timeout = 720

            show = get_item(previous_rating_key)
            oc.add(DirectoryObject(
                key=Callback(MetadataMenu, rating_key=show.rating_key, title=show.title, base_title=show.section.title,
                             previous_item_type="section", display_items=True, randomize=timestamp()),
                title=u"< Back to %s" % show.title,
                thumb=show.thumb or default_thumb
            ))
        elif current_kind == "series":
            # it shouldn't take more than 6 minutes to scan all of a series' files and determine the force refresh
            timeout = 3600

        items = get_all_items(key="children", value=rating_key, base="library/metadata")
        kind, deeper = get_items_info(items)
        dig_tree(oc, items, MetadataMenu,
                 pass_kwargs={"base_title": title, "display_items": deeper, "previous_item_type": kind,
                              "previous_rating_key": rating_key})

        # we don't know exactly where we are here, only add ignore option to series
        if current_kind in ("series", "season"):
            item = get_item(rating_key)
            sub_title = get_item_title(item)
            add_ignore_options(oc, current_kind, title=sub_title, rating_key=rating_key, callback_menu=IgnoreMenu)

        # mass-extract embedded
        if current_kind == "season" and config.plex_transcoder:
            for lang in config.lang_list:
                oc.add(DirectoryObject(
                    key=Callback(SeasonExtractEmbedded, rating_key=rating_key, language=lang,
                                 base_title=show.section.title, display_items=display_items, item_title=item_title,
                                 title=title,
                                 previous_item_type=previous_item_type, with_mods=True,
                                 previous_rating_key=previous_rating_key, randomize=timestamp()),
                    title=u"Extract missing %s embedded subtitles with default mods" % display_language(lang),
                    summary="Extracts the not yet extracted embedded subtitles of all episodes for the current season "
                            "with all configured default modifications"
                ))
                oc.add(DirectoryObject(
                    key=Callback(SeasonExtractEmbedded, rating_key=rating_key, language=lang,
                                 base_title=show.section.title, display_items=display_items, item_title=item_title,
                                 title=title,
                                 previous_item_type=previous_item_type, with_mods=False,
                                 previous_rating_key=previous_rating_key, randomize=timestamp()),
                    title=u"Extract missing %s embedded subtitles" % display_language(lang),
                    summary="Extracts the not yet extracted embedded subtitles of all episodes for the current season"
                ))

        # add refresh
        oc.add(DirectoryObject(
            key=Callback(RefreshItem, rating_key=rating_key, item_title=title, refresh_kind=current_kind,
                         previous_rating_key=previous_rating_key, timeout=timeout * 1000, randomize=timestamp()),
            title=u"Refresh: %s" % item_title,
            summary="Refreshes the %s, possibly searching for missing and picking up new subtitles on disk" % current_kind
        ))
        oc.add(DirectoryObject(
            key=Callback(RefreshItem, rating_key=rating_key, item_title=title, force=True,
                         refresh_kind=current_kind, previous_rating_key=previous_rating_key, timeout=timeout * 1000,
                         randomize=timestamp()),
            title=u"Auto-Find subtitles: %s" % item_title,
            summary="Issues a forced refresh, ignoring known subtitles and searching for new ones"
        ))
    else:
        return ItemDetailsMenu(rating_key=rating_key, title=title, item_title=item_title)

    return oc


@route(PREFIX + '/season/extract_embedded/{rating_key}/{language}')
def SeasonExtractEmbedded(**kwargs):
    rating_key = kwargs.get("rating_key")
    requested_language = kwargs.pop("language")
    with_mods = kwargs.pop("with_mods")
    item_title = kwargs.pop("item_title")
    title = kwargs.pop("title")

    Thread.Create(season_extract_embedded, **{"rating_key": rating_key, "requested_language": requested_language,
                                              "with_mods": with_mods})

    kwargs["header"] = 'Success'
    kwargs["message"] = u"Extracting of embedded subtitles for %s triggered" % title

    kwargs.pop("randomize")
    return MetadataMenu(randomize=timestamp(), title=item_title, **kwargs)


def season_extract_embedded(rating_key, requested_language, with_mods=False):
    # get stored subtitle info for item id
    subtitle_storage = get_subtitle_storage()

    try:
        for data in get_all_items(key="children", value=rating_key, base="library/metadata"):
            item = get_item(data[MI_KEY])
            if item:
                stored_subs = subtitle_storage.load_or_new(item)
                for part in get_all_parts(item):
                    embedded_subs = stored_subs.get_by_provider(part.id, requested_language, "embedded")
                    if not embedded_subs:
                        stream_data = get_embedded_subtitle_streams(part, requested_language=requested_language,
                                                                    get_forced=config.forced_only)
                        if stream_data:
                            stream = stream_data[0]["stream"]

                            extract_embedded_sub(rating_key=item.rating_key, part_id=part.id,
                                                 stream_index=str(stream.index),
                                                 language=requested_language, with_mods=with_mods)
    finally:
        subtitle_storage.destroy()


@route(PREFIX + '/ignore_list')
def IgnoreListMenu():
    oc = SubFolderObjectContainer(title2="Ignore list", replace_parent=True)
    for key in ignore_list.key_order:
        values = ignore_list[key]
        for value in values:
            add_ignore_options(oc, key, title=ignore_list.get_title(key, value), rating_key=value,
                               callback_menu=IgnoreMenu)
    return oc


@route(PREFIX + '/history')
def HistoryMenu():
    from support.history import get_history
    history = get_history()
    oc = SubFolderObjectContainer(title2="History", replace_parent=True)

    for item in history.items:
        possible_language = item.language
        language_display = item.lang_name if not possible_language else display_language(possible_language)

        oc.add(DirectoryObject(
            key=Callback(ItemDetailsMenu, title=item.title, item_title=item.item_title,
                         rating_key=item.rating_key),
            title=u"%s (%s)" % (item.item_title, item.mode_verbose),
            summary=u"%s in %s (%s, score: %s), %s" % (language_display, item.section_title,
                                                       item.provider_name, item.score, df(item.time))
        ))

    history.destroy()

    return oc


@route(PREFIX + '/missing/refresh')
@debounce
def RefreshMissing(randomize=None):
    scheduler.dispatch_task("SearchAllRecentlyAddedMissing")
    header = "Refresh of recently added items with missing subtitles triggered"
    return fatality(header=header, replace_parent=True)


def replace_item(obj, key, replace_value):
    for k, v in obj.items():
        if isinstance(v, dict):
            obj[k] = replace_item(v, key, replace_value)
    if key in obj:
        obj[key] = replace_value
    return obj


@route(PREFIX + '/ValidatePrefs', enforce_route=True)
def ValidatePrefs():
    Core.log.setLevel(logging.DEBUG)

    if Prefs["log_console"]:
        Core.log.addHandler(logger.console_handler)
        Log.Debug("Logging to console from now on")
    else:
        Core.log.removeHandler(logger.console_handler)
        Log.Debug("Stop logging to console")

    # cache the channel state
    update_dict = False
    restart = False

    # reset pin
    Dict["pin_correct_time"] = None

    config.initialize()
    if "channel_enabled" not in Dict:
        update_dict = True

    elif Dict["channel_enabled"] != config.enable_channel:
        Log.Debug("Channel features %s, restarting plugin", "enabled" if config.enable_channel else "disabled")
        update_dict = True
        restart = True

    if "plugin_pin_mode" not in Dict:
        update_dict = True

    elif Dict["plugin_pin_mode"] != Prefs["plugin_pin_mode"]:
        update_dict = True
        restart = True

    if update_dict:
        Dict["channel_enabled"] = config.enable_channel
        Dict["plugin_pin_mode"] = Prefs["plugin_pin_mode"]
        Dict.Save()

    if restart:
        scheduler.stop()
        DispatchRestart()
        return

    scheduler.setup_tasks()
    scheduler.clear_task_data("MissingSubtitles")
    set_refresh_menu_state(None)

    Log.Debug("Validate Prefs called.")

    # SZ config debug
    Log.Debug("--- SZ Config-Debug ---")
    for attr in [
            "version", "app_support_path", "data_path", "data_items_path", "enable_agent",
            "enable_channel", "permissions_ok", "missing_permissions", "fs_encoding",
            "subtitle_destination_folder", "new_style_cache", "dbm_supported", "lang_list", "providers",
            "plex_transcoder", "refiner_settings"]:

        value = getattr(config, attr)
        if isinstance(value, dict):
            d = replace_item(copy.deepcopy(value), "api_key", "xxxxxxxxxxxxxxxxxxxxxxxxx")
            Log.Debug("config.%s: %s", attr, d)
            continue

        Log.Debug("config.%s: %s", attr, value)

    for attr in ["plugin_log_path", "server_log_path"]:
        value = getattr(config, attr)

        if value:
            access = os.access(value, os.R_OK)
            if Core.runtime.os == "Windows":
                try:
                    f = open(value, "r")
                    f.read(1)
                    f.close()
                except:
                    access = False

        Log.Debug("config.%s: %s (accessible: %s)", attr, value, access)

    for attr in [
            "subtitles.save.filesystem", ]:
        Log.Debug("Pref.%s: %s", attr, Prefs[attr])

    # debug drone
    if "sonarr" in config.refiner_settings or "radarr" in config.refiner_settings:
        Log.Debug("----- Connections -----")
        from subliminal_patch.refiners.drone import SonarrClient, RadarrClient
        for key, cls in [("sonarr", SonarrClient), ("radarr", RadarrClient)]:
            if key in config.refiner_settings:
                cname = key.capitalize()
                try:
                    status = cls(**config.refiner_settings[key]).status()
                except HTTPError, e:
                    if e.response.status_code == 401:
                        Log.Debug("%s: NOT WORKING - BAD API KEY", cname)
                    else:
                        Log.Debug("%s: NOT WORKING - %s", cname, traceback.format_exc())
                except:
                    Log.Debug("%s: NOT WORKING - %s", cname, traceback.format_exc())
                else:
                    if status["version"]:
                        Log.Debug("%s: OK - %s", cname, status["version"])
                    else:
                        Log.Debug("%s: NOT WORKING - %s", cname)

    # fixme: check existance of and os access of logs
    Log.Debug("----- Environment -----")
    Log.Debug("Platform: %s", Core.runtime.platform)
    Log.Debug("OS: %s", Core.runtime.os)
    Log.Debug("Python: %s", platform.python_version())
    for key, value in os.environ.iteritems():
        if key.startswith("PLEX") or key.startswith("SZ_"):
            if "TOKEN" in key:
                outval = "xxxxxxxxxxxxxxxxxxx"

            else:
                outval = value
            Log.Debug("%s: %s", key, outval)
    Log.Debug("Locale: %s", locale.getdefaultlocale())
    Log.Debug("-----------------------")

    Log.Debug("Setting log-level to %s", Prefs["log_level"])
    logger.register_logging_handler(DEPENDENCY_MODULE_NAMES, level=Prefs["log_level"])
    Core.log.setLevel(logging.getLevelName(Prefs["log_level"]))
    os.environ['U1pfT01EQl9LRVk'] = '789CF30DAC2C8B0AF433F5C9AD34290A712DF30D7135F12D0FB3E502006FDE081E'

    return
