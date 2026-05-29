# License: dual — GPL-3.0 (code) OR CC BY-SA-NS (prose), recipient's choice

This repository is **dual-licensed**, applied per content type:

- **Code** (everything under `driver/`, any `.py`/`.sh`/`.go`/etc. files, build scripts, configs) —
  [GNU General Public License v3.0](LICENSE-GPL-3.0.txt). Standard code copyleft.

- **Prose** (`README.md`, `WORKLOG.md`, `docs/`, any other Markdown/text content) —
  [Creative Commons Attribution-ShareAlike 4.0](https://creativecommons.org/licenses/by-sa/4.0/)
  with the additional **Network Services clause** (see below). Same terms as
  [`swebench-pro`](https://github.com/kimjune01/swebench-pro)'s LICENSE.md.

Files that mix both (e.g., a Markdown skill file with embedded code) are dual-licensed: recipients
may use them under either, at their choice. This matches the pattern in `swebench-pro/skills/`.

## The Network Services clause (applies to prose-licensed content)

> If you use a Derivative Work to provide a service over a computer network, you must make the
> Corresponding Source of the Derivative Work available to users of the service, under the terms
> of this license or a Compatible License, at no charge.

## Definitions

**Corresponding Source** means the complete source material from which the Derivative Work can be
regenerated: the original prose, code, and configuration; any modifications to them; and any build
instructions (prompts, scripts, workflows) used in the compilation.

## Why dual

Different recipients have different downstream needs. A GPL-only project incorporating our skills
or operator scripts uses the GPL leg cleanly. A documentation/teaching site quoting our prose uses
the CC leg cleanly. Dual licensing means neither party has to fight an upstream license mismatch.
