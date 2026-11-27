# Signature themes (3.35.0)

Nine curated themes, each with a light and a dark version, chosen per person in
Settings > Appearance. Classic Cyan is the existing look, unchanged, and the
default for anyone who has not chosen.

## How it works

- **Registry:** `frontend/src/lib/appearance.ts` lists the nine theme ids and
  names. Only ids are stored, never colors.
- **Colors:** `frontend/src/design/themes.css` redefines the shared semantic
  tokens (`--background`, `--card`, `--surface`, `--primary`, `--border`,
  `--input`, `--warning`, `--destructive`, `--state-done`, chart series and so
  on) under `[data-palette="<id>"]` for dark and
  `[data-palette="<id>"][data-theme="light"]` for light. Every component already
  reads those tokens, so no component has theme-specific code. Classic needs no
  block: it is the existing token set.
- **Mode:** light, dark or system, as before, through `data-theme` on `<html>`.
  Theme and mode are separate choices; the header button still cycles the mode.
- **Previews:** each card in Settings is a miniature OfferPath screen carrying
  its own `data-palette` and `data-theme`, so it is drawn from that theme's real
  tokens.

## Personal preference

- **Identity:** administrators by their stable `user_id` (`admin:<id>`; the
  single-administrator install uses `admin:local`), bidders by `bidder_id`.
  Never by name, email, role label or workspace.
- **Storage:** `localStorage` key `offerpath.appearance.v1:<identity>` holding
  `{theme, mode}`, validated on read; invalid or corrupted values fall back to
  Classic. The server has no per-person preference store, and adding one would
  mean changing the shared gateway, so the preference lives in the browser.
  **Limitation:** a person's theme does not follow them to another computer or
  browser.
- **Before sign-in:** Classic, with this browser's existing mode
  (`mailcheck.theme`), exactly as before the feature.
- **At sign-in:** the person's own theme is applied in a layout effect, before
  the first paint of their session. On sign-out the page returns to Classic.
- **First use:** someone who has never chosen gets Classic and this browser's
  existing mode, so nobody's mode changes on upgrade. No one ever sees another
  person's theme.
- **Reset:** Settings > Appearance > Reset appearance returns that person to
  Classic Cyan, dark, and removes only their stored preference.
- **Failure:** if the browser refuses to store the choice, the theme still
  applies and a message says it will not be remembered.

## Deviations from the brief's palettes

The surface, text, boundary and accent values are used exactly as specified;
all 1,344 checked pairs already met WCAG AA. Changes are confined to semantic
colors that would have been confused with a theme's accent, plus derived
values:

| Theme | Change | Why |
| --- | --- | --- |
| Forest | Success → teal (`#7CCAC0` dark, `#16685E` light) | Botanical green accent looked like "done" |
| Champagne | Warning → orange-amber (`#F0A766`, `#9C4A00`) | Champagne accent looked like a warning |
| Bordeaux | Danger → true red (`#FF9C8F`, `#B3261E`) | Rose accent looked like an error |
| Iris | Processing → blue-violet (`#9FB6F2`, `#3757A6`) | Lavender accent looked like processing |
| Cobalt | Information → teal (`#7CC7D6`, `#16656F`) | Blue accent looked like information |
| Terracotta | Warning → yellow (`#E5C56A`, `#735C00`); danger → raspberry (`#F59AB0`, `#A62B53`) | Copper accent sat between warning and error |
| All | Light chart series derived from the dark pools: same hue, darkened in OKLab until 3.2:1 on the workspace | Brief gave dark pools only |
| All | Calendar event fills in dark signature themes mix each account's own accent into the theme surface | Accounts keep their identity color on every background |
| All | Selected-tab counts blend the accent toward the text color | Cobalt dark measured 4.11:1 before |

## Palettes (final)

### Dark

| Theme | Canvas | Workspace | Panel | Elevated | Input | Hover | Selected | Separator | Control | Accent | On accent | Text | Secondary | Muted |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Iris | `#151319` | `#1B191F` | `#25232A` | `#302D35` | `#1B191F` | `#34313A` | `#383044` | `#39353E` | `#817989` | `#C4B2F3` | `#21182F` | `#F3EFE9` | `#C2BDC6` | `#A29BAA` |
| Midnight | `#131824` | `#171E2B` | `#202838` | `#293345` | `#151C29` | `#303B50` | `#303D60` | `#39445A` | `#7786A0` | `#AEBEFA` | `#17213D` | `#EDF0F8` | `#BAC5D8` | `#A0AEC6` |
| Forest | `#141B17` | `#19221C` | `#222C25` | `#2B372E` | `#17201A` | `#303E34` | `#314637` | `#39473D` | `#748A79` | `#A9D2A6` | `#192B1D` | `#F0F2E9` | `#BBCABD` | `#A6B6A9` |
| Champagne | `#1B1714` | `#221D19` | `#2B2520` | `#362E28` | `#201B17` | `#3B322B` | `#44372B` | `#473B32` | `#8D7968` | `#DCC6A3` | `#302419` | `#F4EEE5` | `#CDBEAE` | `#B2A293` |
| Bordeaux | `#1C151B` | `#241B23` | `#30232D` | `#3B2C37` | `#211920` | `#40313B` | `#4A3341` | `#4B3945` | `#907584` | `#E0B2C2` | `#351D2B` | `#F5EDF1` | `#D0BEC8` | `#B5A0AC` |
| Monograph | `#141414` | `#1B1B1B` | `#242424` | `#303030` | `#191919` | `#353535` | `#3B3B3B` | `#3D3D3D` | `#808080` | `#E1E1DF` | `#1C1C1C` | `#F5F5F3` | `#C3C3C1` | `#A5A5A3` |
| Cobalt | `#171B22` | `#1C222C` | `#252E3A` | `#303B49` | `#19212B` | `#354353` | `#283D61` | `#3B4657` | `#78899F` | `#90B3FF` | `#172642` | `#F0F2F6` | `#BEC8D7` | `#A0AFC2` |
| Terracotta | `#1D1816` | `#261E1B` | `#302622` | `#3B2E28` | `#221B18` | `#41332D` | `#4B352D` | `#4D3D35` | `#90796C` | `#E4A991` | `#382219` | `#F6EEE7` | `#D1BEB2` | `#B6A095` |

| Theme | Success | Information | Warning | Danger | Processing | Chart series 0–9 |
| --- | --- | --- | --- | --- | --- | --- |
| Iris | `#86C6A4` on `#26392F` | `#8EBDE8` on `#293747` | `#E9BB79` on `#413426` | `#F1A0A8` on `#402A32` | `#9FB6F2` on `#2B3348` | `#A99ACF` `#85BDA4` `#8EACD0` `#DCB580` `#D394AA` `#78B7B3` `#D49B83` `#B7C98D` `#B8A39D` `#D3CBDD` |
| Midnight | `#86C6A4` on `#26392F` | `#8EBDE8` on `#293747` | `#E9BB79` on `#413426` | `#F1A0A8` on `#402A32` | `#C9B7EA` on `#393046` | `#AEBEFA` `#70C5B5` `#E0B979` `#C39AE0` `#E3949E` `#8AA8C8` `#A5CC83` `#C49C84` `#78B9E5` `#C6CBD8` |
| Forest | `#7CCAC0` on `#21393A` | `#8EBDE8` on `#293747` | `#E9BB79` on `#413426` | `#F1A0A8` on `#402A32` | `#C9B7EA` on `#393046` | `#A9D2A6` `#8DBFD0` `#E0BA83` `#B5A2D4` `#D99EAB` `#75B9A9` `#D29C7C` `#9CA9D4` `#C5C989` `#C5D0C5` |
| Champagne | `#86C6A4` on `#26392F` | `#8EBDE8` on `#293747` | `#F0A766` on `#45301F` | `#F1A0A8` on `#402A32` | `#C9B7EA` on `#393046` | `#DCC6A3` `#91B9AD` `#93ACD0` `#C0A0D4` `#D99BA3` `#A9BF89` `#77B9C4` `#D79E7A` `#A5A7BE` `#C5B9B0` |
| Bordeaux | `#86C6A4` on `#26392F` | `#8EBDE8` on `#293747` | `#E9BB79` on `#413426` | `#FF9C8F` on `#47282A` | `#C9B7EA` on `#393046` | `#E0B2C2` `#91C4AC` `#9DB6E4` `#E2BC82` `#C1A6DA` `#7ABCB7` `#D39B82` `#B8CC92` `#A7A9C6` `#D0C1CA` |
| Monograph | `#86C6A4` on `#26392F` | `#8EBDE8` on `#293747` | `#E9BB79` on `#413426` | `#F1A0A8` on `#402A32` | `#C9B7EA` on `#393046` | `#B9C5D6` `#8FC3AA` `#D5B77D` `#A99BD0` `#D397A5` `#7FBAC4` `#CF9B83` `#B6C58F` `#929DAC` `#DEDEDE` |
| Cobalt | `#86C6A4` on `#26392F` | `#7CC7D6` on `#223A40` | `#E9BB79` on `#413426` | `#F1A0A8` on `#402A32` | `#C9B7EA` on `#393046` | `#90B3FF` `#81C7B1` `#E2BE7D` `#B69DE0` `#DE96AA` `#79BACA` `#D59F83` `#B5CB8D` `#A8B6D1` `#D3D9E4` |
| Terracotta | `#86C6A4` on `#26392F` | `#8EBDE8` on `#293747` | `#E5C56A` on `#3F3622` | `#F59AB0` on `#46283A` | `#C9B7EA` on `#393046` | `#E4A991` `#8DC1AB` `#90B0D8` `#D8C282` `#C3A5D5` `#7BBAB7` `#D69CAD` `#B4C58D` `#A9ABB9` `#D7C8B9` |

### Light

| Theme | Canvas | Workspace | Panel | Elevated | Input | Hover | Selected | Separator | Control | Accent | On accent | Text | Secondary | Muted |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Iris | `#F0EDE8` | `#F8F5F1` | `#FFFFFF` | `#FFFFFF` | `#FFFFFF` | `#EDE8F0` | `#E9E0F8` | `#DED8E0` | `#847A8D` | `#62469A` | `#FFFFFF` | `#26232B` | `#625B69` | `#6B6371` |
| Midnight | `#E9EDF6` | `#F5F7FC` | `#FFFFFF` | `#FFFFFF` | `#FFFFFF` | `#E8EDF7` | `#E0E7FB` | `#D7DFED` | `#7786A0` | `#3F55A4` | `#FFFFFF` | `#20283A` | `#4F5C75` | `#59667C` |
| Forest | `#E9EDE5` | `#F5F7F1` | `#FFFFFF` | `#FFFFFF` | `#FFFFFF` | `#E8EEE5` | `#DFEBDD` | `#D5DED3` | `#788A79` | `#356343` | `#FFFFFF` | `#243129` | `#4F6253` | `#59695D` |
| Champagne | `#EFE8DF` | `#F8F4EE` | `#FFFCF7` | `#FFFFFF` | `#FFFCF7` | `#EEE5D9` | `#EDE0CC` | `#E0D4C6` | `#947F68` | `#74532E` | `#FFFFFF` | `#332820` | `#655444` | `#6D5C4B` |
| Bordeaux | `#F0E8ED` | `#FAF5F8` | `#FFFFFF` | `#FFFFFF` | `#FFFFFF` | `#F1E6ED` | `#F0DCE6` | `#E2D3DC` | `#947888` | `#8A4265` | `#FFFFFF` | `#34242F` | `#6A5060` | `#705565` |
| Monograph | `#EDEDEB` | `#F7F7F5` | `#FFFFFF` | `#FFFFFF` | `#FFFFFF` | `#EBEBE9` | `#E3E3E0` | `#DADAD7` | `#80807D` | `#373737` | `#FFFFFF` | `#222222` | `#555552` | `#626260` |
| Cobalt | `#EEEDE8` | `#F7F6F1` | `#FFFFFF` | `#FFFFFF` | `#FFFFFF` | `#E8EAF0` | `#DCE6FD` | `#DADDDC` | `#7C8492` | `#244FBA` | `#FFFFFF` | `#252B36` | `#525D6E` | `#596579` |
| Terracotta | `#F1E8E0` | `#FBF6F0` | `#FFFFFF` | `#FFFFFF` | `#FFFFFF` | `#F3E6DD` | `#F2DDD2` | `#E4D5CA` | `#997D6B` | `#914B35` | `#FFFFFF` | `#362A24` | `#69564B` | `#6F594D` |

| Theme | Success | Information | Warning | Danger | Processing | Chart series 0–9 |
| --- | --- | --- | --- | --- | --- | --- |
| Iris | `#256749` on `#E5F1E9` | `#285D96` on `#E7EFF9` | `#82530F` on `#FFF1D9` | `#A33745` on `#FAE5E8` | `#3757A6` on `#E6ECFA` | `#9180B9` `#54967B` `#698AB2` `#AE813F` `#B7738C` `#48938F` `#B87A60` `#7B8F44` `#9B847D` `#8F859B` |
| Midnight | `#256749` on `#E5F1E9` | `#285D96` on `#E7EFF9` | `#82530F` on `#FFF1D9` | `#A33745` on `#FAE5E8` | `#694AA0` on `#EEE7FA` | `#7484CB` `#219987` `#B0822C` `#A678C5` `#C46E7B` `#6C8DAF` `#69963A` `#AA7F65` `#4291C2` `#848A99` |
| Forest | `#16685E` on `#E1F1EE` | `#285D96` on `#E7EFF9` | `#82530F` on `#FFF1D9` | `#A33745` on `#FAE5E8` | `#694AA0` on `#EEE7FA` | `#649661` `#5592A5` `#AD8039` `#947FB6` `#B77686` `#449684` `#B67B58` `#7987B6` `#8B8E3C` `#7F8C7F` |
| Champagne | `#256749` on `#E5F1E9` | `#285D96` on `#E7EFF9` | `#9C4A00` on `#FDEBDA` | `#A33745` on `#FAE5E8` | `#694AA0` on `#EEE7FA` | `#9E8458` `#618F82` `#6F8AB2` `#9D79B3` `#B7737D` `#768F4F` `#41929F` `#B87A51` `#83859E` `#92847A` |
| Bordeaux | `#256749` on `#E5F1E9` | `#285D96` on `#E7EFF9` | `#82530F` on `#FFF1D9` | `#B3261E` on `#FBE5E2` | `#694AA0` on `#EEE7FA` | `#AF7A8E` `#579479` `#6F8ABE` `#AF8236` `#9B7CB6` `#459590` `#B77A5F` `#7C924A` `#8587A7` `#978590` |
| Monograph | `#256749` on `#E5F1E9` | `#285D96` on `#E7EFF9` | `#82530F` on `#FFF1D9` | `#A33745` on `#FAE5E8` | `#694AA0` on `#EEE7FA` | `#7C8A9E` `#58967A` `#A7843B` `#9181BA` `#B77686` `#4C939F` `#B37B60` `#819150` `#7F8B9B` `#898989` |
| Cobalt | `#256749` on `#E5F1E9` | `#16656F` on `#E1F0F2` | `#82530F` on `#FFF1D9` | `#A33745` on `#FAE5E8` | `#694AA0` on `#EEE7FA` | `#6086DC` `#3D987F` `#AC8125` `#987CC5` `#BF7188` `#4493A5` `#B67B5C` `#789144` `#7888A6` `#808895` |
| Terracotta | `#256749` on `#E5F1E9` | `#285D96` on `#E7EFF9` | `#735C00` on `#FBF2D2` | `#A62B53` on `#FAE3EA` | `#694AA0` on `#EEE7FA` | `#BA775C` `#56947C` `#678BB7` `#A18630` `#9D7BB1` `#4B9693` `#B7788B` `#7E914E` `#878998` `#988674` |

## Verification

- **Contrast, computed:** 1,344 foreground and background pairs across the 16
  signature combinations (text on every surface including hover and selected,
  accent as text, text on accent, semantic colors on surfaces and on their own
  tints, control boundaries and focus at 3:1, every chart series at 3:1). All
  pass; the tightest is muted text on a selected row at 4.52:1.
- **Contrast, rendered:** axe-core WCAG 2.2 A/AA on 8 pages in all 18
  combinations (144 audits): no violations after one fix.
- **Keyboard focus:** 309 focus stops visible in Monograph dark and light,
  Champagne light and Forest dark.
- **Isolation (real Settings UI, identities swapped):** 16 of 16 steps passed:
  A Iris Dark and B Midnight Light kept apart across sign-ins; owner Monograph
  leaves both unchanged; A keeps Iris after a workspace switch and after a
  browser restart; resetting A leaves B and the owner untouched; sign-out
  returns to Classic; only the people who chose have stored keys.
- **Unit tests:** `frontend/src/lib/appearance.test.ts` (6 tests).
- **No disturbance:** switching themes twice took 139 ms with no API requests;
  an unsaved Settings edit, the Save bar and the scroll position were kept.
- **Residual cyan:** every element on 8 pages in all 16 signature combinations
  was scanned for Classic's cyan; none remains (flagged teal legend swatches are
  the themes' own chart colors).
- **Parity:** against the 3.34.0 build, only Settings differs, by the added
  Appearance controls (1 link, 12 options, 1 button); the other 18 views match.
- **Tests and build:** TypeScript, production build, 657 frontend tests, theme
  contrast and release tests, `release.py --check`.

Screenshots in `themes/`: one sheet per theme (dashboard dark and light, triage
dark, bidder management light), the selector, calendar events, and combined
spreadsheet states.

## Not verified

- Cross-device preference (not supported, see Limitation).
- Real Windows high-contrast themes, Windows display scaling and real phones.
- Forced colors and phone widths were not rerun per theme.
- The sign-in screen always uses Classic, because the person is not known yet.
