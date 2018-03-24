# coding=utf-8

import re

from subzero.language import Language
from subzero.modification.mods import SubtitleTextModification, empty_line_post_processors, SubtitleModification
from subzero.modification.processors.string_processor import StringProcessor
from subzero.modification.processors.re_processor import NReProcessor
from subzero.modification import registry


class CommonFixes(SubtitleTextModification):
    identifier = "common"
    description = "Basic common fixes"
    exclusive = True
    order = 40

    long_description = """\
    Fix common and whitespace/punctuation issues in subtitles
    """

    processors = [
        # -- = em dash
        NReProcessor(re.compile(r'(?u)(\w|\b|\s|^)(-\s?-{1,2})'), ur"\1—", name="CM_multidash"),

        # line = _/-/\s
        NReProcessor(re.compile(r'(?u)(^[-_\s.]*[-_\s.]+[-_\s.]*$)'), "", name="CM_non_word_only"),

        # fix music symbols
        NReProcessor(re.compile(ur'(?u)(^[*#¶\s]*[*#¶]+[*#¶\s]*$)'), u"♪", name="CM_music_symbols"),

        # '' = "
        StringProcessor("''", '"', name="CM_double_apostrophe"),

        # remove leading ...
        NReProcessor(re.compile(r'(?u)^\.\.\.[\s]*'), "", name="CM_leading_ellipsis"),

        # remove "downloaded from" tags
        NReProcessor(re.compile(r'(?ui).+downloaded\s+from.+'), "", name="CM_crap"),

        # no space after ellipsis
        NReProcessor(re.compile(r'(?u)\.\.\.(?![\s.,!?\'"])(?!$)'), "... ", name="CM_ellipsis_no_space"),

        # no space before spaced ellipsis
        NReProcessor(re.compile(r'(?u)(?<=[^\s])(?<!\s)\. \. \.'), " . . .", name="CM_ellipsis_no_space2"),

        # multiple spaces
        NReProcessor(re.compile(r'(?u)[\s]{2,}'), " ", name="CM_multiple_spaces"),

        # more than 3 dots
        NReProcessor(re.compile(r'(?u)\.{3,}'), "...", name="CM_dots"),

        # no space after starting dash
        NReProcessor(re.compile(r'(?u)^-(?![\s-])'), "- ", name="CM_dash_space"),

        # remove starting spaced dots (not matching ellipses)
        NReProcessor(re.compile(r'(?u)^(?!\s?(\.\s\.\s\.)|(\s?\.{3}))(?=\.+\s+)[\s.]*'), "",
                     name="CM_starting_spacedots"),

        # space missing before doublequote
        # ReProcessor(re.compile(r'(?u)(?<!^)(?<![\s(\["])("[^"]+")'), r' \1', name="CM_space_before_dblquote"),

        # space missing after doublequote
        # ReProcessor(re.compile(r'(?u)("[^"\s][^"]+")([^\s.,!?)\]]+)'), r"\1 \2", name="CM_space_after_dblquote"),

        # space before ending doublequote?

        # remove >>
        NReProcessor(re.compile(r'(?u)^\s?>>\s*'), "", name="CM_leading_crocodiles"),

        # replace uppercase I with lowercase L in words
        NReProcessor(re.compile(ur'(?u)([a-zà-ž]+)(I+)'),
                     lambda match: ur'%s%s' % (match.group(1), "l" * len(match.group(2))),
                     name="CM_uppercase_i_in_word"),

        # fix spaces in numbers (allows for punctuation: ,.:' (comma/dot only fixed if after space, those may be
        # countdowns otherwise); don't break up ellipses
        NReProcessor(
            re.compile(r'(?u)(\b[0-9]+[0-9:\']*(?<!\.\.)\s+(?!\.\.)[0-9,.:\'\s]*(?=[0-9]+)[0-9,.:\'])'),
            lambda match: match.group(1).replace(" ", "") if match.group(1).count(" ") == 1 else match.group(1),
            name="CM_spaces_in_numbers"),

        # uppercase after dot
        NReProcessor(re.compile(ur'(?u)((?<!(?=\s*[A-ZÀ-Ž-_0-9.]\s*))(?:[^.\s])+\.\s+)([a-zà-ž])'),
                     lambda match: ur'%s%s' % (match.group(1), match.group(2).upper()), name="CM_uppercase_after_dot"),

        # remove double interpunction
        NReProcessor(re.compile(ur'(?u)(\s*[,!?])\s*([,.!?][,.!?\s]*)'),
                     lambda match: match.group(1).strip() + (" " if match.group(2).endswith(" ") else ""),
                     name="CM_double_interpunct"),

        # remove spaces before punctuation; don't break spaced ellipses
        NReProcessor(re.compile(r'(?u)(?:(?<=^)|(?<=\w)) +([!?.,](?![!?.,]| \.))'), r"\1", name="CM_punctuation_space"),
    ]

    post_processors = empty_line_post_processors


class RemoveTags(SubtitleModification):
    identifier = "remove_tags"
    description = "Remove all style tags"
    exclusive = True
    modifies_whole_file = True

    long_description = """\
    Removes all possible style tags from the subtitle, such as font, bold, color etc.
    """

    def modify(self, content, debug=False, parent=None, **kwargs):
        for entry in parent.f:
            # this actually plaintexts the entry and by re-assigning it to plaintext, it replaces \n with \N again
            entry.plaintext = entry.plaintext


class ReverseRTL(SubtitleModification):
    identifier = "reverse_rtl"
    description = "Reverse punctuation in RTL languages"
    exclusive = True
    order = 50
    languages = [Language("heb")]

    long_description = """\
    Some playback devices don't properly handle right-to-left markers for punctuation. Physically swap punctuation.
    Applicable to languages: hebrew
    """

    processors = [
        # new? (?u)(^([\s.!?]*)(.+?)(\s*)(-?\s*)$); \5\4\3\2
        #NReProcessor(re.compile(ur"(?u)((?=(?<=\b|^)|(?<=\s))([.!?-]+)([^.!?-]+)(?=\b|$|\s))"), r"\3\2",
        #             name="CM_RTL_reverse")
        NReProcessor(re.compile(ur"(?u)(^([\s.!?]*)(.+?)(\s*)(-?\s*)$)"), r"\5\4\3\2",
                     name="CM_RTL_reverse")
    ]


registry.register(CommonFixes)
registry.register(RemoveTags)
registry.register(ReverseRTL)
