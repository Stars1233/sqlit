# Custom Keymaps

sqlit lets you override individual keybindings via a JSON file. Your overrides merge over the built-in defaults, so you only list what you want to change — anything you don't touch keeps its default behaviour. The footer hints and help screen (`?`) automatically reflect your custom keys.

## Quick start

1. Create the keymaps directory and copy the template:
   ```bash
   mkdir -p ~/.sqlit/keymaps
   cp config/keymap.template.json ~/.sqlit/keymaps/my-custom.json
   ```

2. Edit `~/.sqlit/keymaps/my-custom.json` and replace the example overrides with the ones you want.

3. Enable it by adding to `~/.sqlit/settings.json`:
   ```json
   { "custom_keymap": "my-custom" }
   ```
   Use the filename without `.json`. To go back to defaults, set `"custom_keymap": "default"` or remove the key.

4. Restart sqlit.

## How merging works

There are two binding types:

| Type | Identity for merging | What "override" means |
|------|----------------------|-----------------------|
| `action_keys` | `(action, context)` | Replaces the default's *primary* key for that action/context |
| `leader_commands` | `(action, menu)` | Replaces the default leader key for that action in that menu |

If your entry's identity matches a default, the default's primary slot is taken over by your entry. **Secondary defaults survive** — e.g. tree navigation has `j` (primary) plus `down` (alias); rebinding `j` doesn't kill `down`. If your entry doesn't match any default, it's added as a new binding.

Because identity is `(action, ...)` and not `(key, ...)`, the cleanest way to remap is to specify the action you want to rebind and the new key. Optional fields (`label`, `category`, `guard`, `primary`, `show`, `priority`) are inherited from the matching default — you only need to repeat them when adding a brand-new binding that has no default.

## Validation at startup

sqlit validates the merged keymap before the app boots. If your overrides introduce a conflict (the same key bound to *different* actions in the same context or menu) the keymap is rejected and sqlit falls back to defaults with a clear stderr message naming the conflicting entries. Default-only overlaps that are disambiguated by runtime state (for example `d` on a connection vs. a folder) are tolerated.

Missing `context` for a context-scoped action is also rejected — silently appending a duplicate global binding is almost never what you wanted. If you really do want a global binding, set `"context": null` explicitly.

### Minimal override examples

Move `Help` from `<leader>h` to `<leader>?`:
```json
{ "key": "question_mark", "action": "show_help" }
```

Use `ctrl+enter` to execute queries in normal mode (overrides the default `<enter>`):
```json
{ "key": "ctrl+enter", "action": "execute_query", "context": "query_normal" }
```

Add a brand-new binding (no matching default — needs `label` and `category`):
```json
{ "key": "R", "action": "refresh_tree", "label": "Refresh tree", "category": "View" }
```

## File format

```json
{
  "keymap": {
    "leader_commands": [ /* leader-key bindings */ ],
    "action_keys":      [ /* direct bindings */ ]
  }
}
```

### `leader_commands` fields

| Field | Required? | Notes |
|-------|-----------|-------|
| `key` | yes | The key pressed after the leader (e.g. `"q"`, `"question_mark"`) |
| `action` | yes | Action name |
| `menu` | only if not `"leader"` | Submenu (e.g. `"delete"`, `"yank"`, `"g"`) |
| `label` | only for new bindings | Display label; inherited from default when overriding |
| `category` | only for new bindings | Group in command menu; inherited when overriding |
| `guard` | optional | e.g. `"has_connection"`; inherited when overriding |

### `action_keys` fields

| Field | Required? | Notes |
|-------|-----------|-------|
| `key` | yes | Key combination (e.g. `"i"`, `"ctrl+q"`, `"escape"`) |
| `action` | yes | Action name |
| `context` | optional | e.g. `"query_normal"`, `"tree"`, `"results"`; `null` means global-no-context |
| `guard` | optional | Inherited when overriding |
| `primary` | optional, default `true` | Footer/help prefers primary keys |
| `show` | optional, default `false` | Show in Textual's binding hints |
| `priority` | optional, default `false` | Wins over child-widget bindings |

## Special key names

`space`, `escape`, `enter`, `backspace`, `delete`, `tab`, `question_mark`, `slash`, `dollar_sign`, `percent_sign`, `asterisk`, `ctrl+<key>`, `shift+<key>`.

## Common actions

### Global
`quit`, `show_help`, `cancel_operation`, `leader_key`

### Navigation (context: `navigation`)
`focus_explorer`, `focus_query`, `focus_results`

### Connection
`show_connection_picker`, `disconnect`, `new_connection`

### Query editor (context: `query_normal`)
`enter_insert_mode`, `prepend_insert_mode`, `append_insert_mode`, `append_line_end`,
`open_line_below`, `open_line_above`, `execute_query`,
`show_history`, `new_query`, `undo`, `redo`,
`yank_leader_key`, `delete_leader_key`, `change_leader_key`, `g_leader_key`,
`paste`

### Query editor (context: `query_insert`)
`exit_insert_mode`, `execute_query_insert`, `autocomplete_accept`,
`select_all`, `copy_selection`, `paste`

### Vim cursor movement (context: `query_normal`)
`cursor_left`, `cursor_down`, `cursor_up`, `cursor_right`,
`cursor_word_forward`, `cursor_WORD_forward`,
`cursor_word_back`, `cursor_WORD_back`,
`cursor_line_start`, `cursor_line_end`, `cursor_last_line`,
`cursor_find_char`, `cursor_find_char_back`,
`cursor_till_char`, `cursor_till_char_back`,
`cursor_matching_bracket`

### Tree (context: `tree`)
`tree_cursor_up`, `tree_cursor_down`, `tree_filter`, `collapse_tree`, `refresh_tree`,
`select_table`, `new_connection`, `edit_connection`, `delete_connection`,
`duplicate_connection`, `disconnect`

### Results (context: `results`)
`view_cell`, `view_cell_full`, `edit_cell`, `delete_row`,
`results_yank_leader_key`, `clear_results`, `results_filter`,
`results_cursor_left`, `results_cursor_down`, `results_cursor_up`, `results_cursor_right`,
`next_result_section`, `prev_result_section`, `toggle_result_section`

### Autocomplete (context: `autocomplete`)
`autocomplete_next`, `autocomplete_prev`, `autocomplete_close`

## Contexts

`global`, `query_normal`, `query_insert`, `tree`, `tree_filter`, `tree_visual`,
`results`, `results_filter`, `value_view`, `navigation`, `autocomplete`.

## Guards

- `has_connection` — a database connection is active
- `query_executing` — a query is currently running

## Troubleshooting

**Keymap doesn't load.** Make sure `custom_keymap` in `~/.sqlit/settings.json` matches your filename without `.json`. Check the console for `[sqlit] Failed to load custom keymap …`.

**Invalid JSON.** Validate with `python -m json.tool ~/.sqlit/keymaps/my-custom.json`.

**Override is being ignored.** Confirm the `action` and `context`/`menu` exactly match a default. Identity is `(action, context)` for action keys and `(action, menu)` for leader commands — a typo in `context` adds a new binding instead of replacing the default.

## Reverting

Set `"custom_keymap": "default"` in settings, or remove the key entirely.
