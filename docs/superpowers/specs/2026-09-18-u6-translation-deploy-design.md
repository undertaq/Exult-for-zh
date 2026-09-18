# U6 Translation Staging and Deployment

## Goal

Keep release-ready Traditional Chinese game resources inside the repository,
under `tools/u6_translation/deploy`, while allowing the existing generation
pipeline to produce those files and a separate command to copy them into an
Ultima 7 game installation.

## Staged layout

The staging tree mirrors paths below the game root:

```text
tools/u6_translation/deploy/
  patch/
    autonotes.txt
    textmsg.txt
  mods/Ultima6v1.3/patch/
    zh_translation.tsv
```

Only these checked-in, release-ready text artifacts are in scope. The compiled
`patch/usecode.zh` file is intentionally excluded: it is a legacy alternate
usecode binary, is not emitted by this pipeline, and the active U6 runtime uses
the table above for display translation.

## Generation and staging

`emit` keeps accepting an explicit `--output`, but when omitted it writes the
approved table to the staged U6 path. Any conversion performed as part of
emission remains deterministic and Traditional-Chinese-safe. The staged global
text resources are maintained as ordinary checked-in files and are validated by
the same staging manifest; generation scripts must never write directly to an
external game directory.

## Deployment command

Add a `deploy` CLI command backed by a small Python helper. It accepts a game
root, resolves every manifest entry relative to the checked-in staging folder,
creates missing parent directories, and copies files atomically while
preserving file mode and content. It must reject paths that escape the staging
root or target root, fail clearly for missing staged files, and support a
`--dry-run` mode that reports planned copies without changing the game tree.
Repeated deployment is idempotent. The command reports each copied path and a
summary suitable for shell scripts.

## Validation and tests

Tests will verify:

1. the manifest contains exactly the supported staged artifacts;
2. `emit` defaults to the staged table and still honors an explicit output;
3. Traditional-Chinese conversion and file bytes/permissions survive staging;
4. deployment copies the mirrored paths, creates parents, preserves modes, and
   leaves a dry run unchanged;
5. missing or unsafe manifest paths fail before any copy occurs; and
6. a second deployment produces no content changes.

The README will document the staging tree, the default emit destination, and a
typical deployment command such as:

```sh
python3 -m tools.u6_translation deploy --game-root /path/to/Ultima_7
```

