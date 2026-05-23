# Cover Studio

Cover Studio is a local cover-making tool for authors and small publishers. It
can make covers for print-on-demand services, local printers, proof copies,
booklets, and personal book projects.

It helps create wraparound print covers and front-cover images from one saved
cover file.

The project is still early, but the goal is simple: give book creators a cover
workspace that runs on macOS, Windows, and Linux without requiring design
software.

## What It Does

- Builds paperback and hardcover wraparound covers.
- Includes common print-on-demand trim presets.
- Allows custom trim sizes.
- Exports PDF, PNG, and front-cover JPG files.
- Shows a browser-based preview.
- Saves your cover settings in a readable `cover.md` file.
- Supports inches, millimeters, and centimeters in the browser app.
- Lets you choose simple title, bold, body, and italic fonts and colors.
- Includes a guide shift control for checking printer templates.
- Keeps print geometry internally in inches for consistent PDF and raster output.

## What You Need

You need Python 3 installed.

If you are not sure whether Python is installed, open Terminal, Command Prompt,
or PowerShell and run:

```sh
python3 --version
```

On some Windows systems, the command may be:

```sh
python --version
```

This project also needs Pillow and ReportLab. From the `cover-generator` folder,
install them with:

```sh
python3 -m pip install Pillow reportlab
```

On Windows, use `python` instead of `python3` if that is the command your system
recognizes.

## Folder Setup

The easiest setup is to keep this tool beside your book folder.

Example:

```text
MyBooks/
  cover-generator/
  my-book/
    cover/
      cover.md
      assets/
        base.png
```

The `cover.md` file stores the book title, trim size, page count, image paths,
text, colors, and layout adjustments.

## Start The Browser App

Open Terminal, Command Prompt, or PowerShell.

Go to your book folder:

```sh
cd path/to/my-book
```

Start Cover Studio:

```sh
python3 ../cover-generator/web_app.py cover/cover.md --open-browser
```

If your system uses `python` instead of `python3`, use:

```sh
python ../cover-generator/web_app.py cover/cover.md --open-browser
```

The app will print a local address such as:

```text
Cover Studio running at http://127.0.0.1:8765
```

If the browser does not open automatically, copy that address into your browser.

Keep the terminal window open while using the app. Closing it stops the local
app.

## If The Port Is Busy

Sometimes another copy of the app is already running. If that happens, Cover
Studio will try the next port automatically.

You may see:

```text
Port 8765 is already in use; trying 8766.
Cover Studio running at http://127.0.0.1:8766
```

Use the address it prints.

## Export A Cover

In the browser app:

1. Choose the binding: Paperback or Hardcover.
2. Leave the setup preset switch on for common platform presets, or turn it off
   for a custom size.
3. Enter the page count.
4. Check the preview.
5. Click Export.

Output files are written into your book's `cover/` folder.

Typical output names look like:

```text
my-book-pb-cover.pdf
my-book-pb-cover.png
my-book-pb-front.jpg
my-book-front.jpg
```

The binding-specific front-cover file, such as `my-book-pb-front.jpg`, is the
safer file to use because it tells you which binding created it.

## Custom Sizes

Turn off the setup preset switch when your printer needs a size that is not
listed.

The custom fields are:

- Width
- Height
- Spine
- Bleed
- Safe margin

For supported paperback-style presets, Cover Studio can calculate the spine from
the page count. For other printers, check the printer's instructions and enter
the spine width they require.

Custom sizes are useful for local printers, short-run booklets, personal
projects, proof copies, and platforms whose trim sizes are not listed.

## Guides

The Guides checkbox shows trim, spine, hinge, and cover boundary lines in the
preview.

If a printer template appears slightly offset from the generated cover, use
Guide X shift on the Setup tab. Negative numbers move the vertical guide lines
left. Positive numbers move them right. This only changes the visible guides; it
does not change the exported cover dimensions.

## Units

The browser app has a Units control:

- Inches
- Millimeters
- Centimeters

Use whichever unit is natural for you. The app converts the numbers for display
and editing. The saved print geometry remains inch-based internally.

## Fonts

Cover Studio uses four friendly font roles:

- Title
- Bold
- Body
- Italic

The easiest way to use your own fonts is to create this folder in your book
project:

```text
cover/
  fonts/
    Title.ttf
    Bold.ttf
    Regular.ttf
    Italic.ttf
```

You do not need all four files. Add only the ones you want to control.

You can also use the Fonts tab in the browser app and enter a font file path for
any role. Relative paths are resolved from the book folder.

The Fonts tab also has color pickers for:

- Title
- Accent
- Body
- Soft text

Colors are saved as normal HEX values such as `#daa520`.

## Command-Line Export

If you only want to generate files without opening the browser app, run this
from your book folder:

```sh
python3 ../cover-generator/generate_cover.py cover/cover.md --non-interactive
```

To check the cover settings without exporting:

```sh
python3 ../cover-generator/generate_cover.py cover/cover.md --validate-json
```

## Future Packaged Commands

After packaging, the intended commands are:

```sh
cover-studio cover/cover.md --open-browser
cover-export cover/cover.md --non-interactive
```

For now, use the `python3 ../cover-generator/...` commands above.

## Troubleshooting

If the browser shows an old version, refresh the page.

If the terminal says Python is not found, install Python and try again. On
Windows, also try `python` instead of `python3`.

If an image does not appear, check the image path in `cover.md`. Relative paths
are resolved from the book folder.

If export fails, use the validation command:

```sh
python3 ../cover-generator/generate_cover.py cover/cover.md --validate-json
```

The validation output should point to missing images, missing dimensions, or
other problems.

## Project Status

This is a work in progress. The current browser app is meant to prove the
cross-platform workflow and make cover iteration easier. The next major
improvements are smoother live preview, better sliders and controls, project
selection, and direct dragging on the preview.
