Merge greyscale single channel (r,g,b) tiffs into one rgb composite while
applying a simple correction for uneven illumination. 

----
# Dependencies
- Python 2.7 (if you need to install, [Anaconda](https://www.anaconda.com/download/) is recommended)
- openCV
- [PyLibTiff](https://github.com/pearu/pylibtiff)


Usage
-----

Run as an clickable executable or from a terminal. In the popup window select
the folder containing the images to be merged. The merged images will be
written to `merge_corrected/<num>-rgb.tif` by default and **will overwrite
prexisting files in the event of naming conflicts**. See below for more
information on filename conventions. See `./channel_merge.py --help` to see
additional options. 

Image Processing
----------------

Illumination correction method is a guassian blur background subtraction. The
standard deviation of the gaussian kernel (sigma) is selectable via
command-line flags, or by editing the default value within parse_args. The
values of sigma that give acceptable results will likely be heavily dependent
on image set.

Input Filenames
---------------

Metadata about image and channel identity will be extracted from filenames;
trying to ignore bright field images and handle typos. If there's more than one
tiff of a given color channel, will create additional merges of all possible
combinations of rgb channels.

### Naming Conventions
Assumes the following file naming conventions: 
- `<id>-<channel_name>[-#].tif` 
- where `-#` is an optional number in the event of multiple same-channel images, e.g.,

```
    01-red.tif
    23-blue-2.tif   # an alternative blue channel scan of img 23
<<<<<<< HEAD
=======
	14-green3.tif   # an alt green scan of img 14
>>>>>>> dev
```

Whitespace will be replaced with `-`. This *could* overwrite data if you had two files with identical names sans ` ` and `-`. 
e.g.,

	01 red 3.tif >> 01-red-3.tif
	01 red-3.tif >> 01-red-3.tif    # will clobber the file above

Trailing digits are interpreted alternative scan numbers and will be renamed
with a separating `-`. This, again, has clobber potential,
e.g.,

	01-red2.tif  >> 01-red-2.tif
	01-red 2.tif >> 01-red-2.tif    # will clobber the file above
	01 red 2.tif >> 01-red-2.tif    # will clobber the file above

### Spelling Errors
The first letter of a file's `channel_name` is taken to imply it's color.
e.g.,

	01-reed.tif        # red
	44-guleinoiena.tif # green
	10-b.tif           # blue
	10-bfue.tif        # excluded (see Brightfield Exclusion below)

### Brightfield Exclusion
Any .tif with a `channel_name` *starting with* `bf` is assumed to be a brightfield image and is excluded from any merges. So as long as blue channels are not named `bf*` things should be okay.
e.g.,

	01-bf.tif, 01-bflue.tif, 01-bf_actuallybluetrustme.tif # excluded
	01-bl.tif, 01-blbfue.tif  # blue


Issues
------

Written assuming less than 100 input image groups. Files w/ 3 digit prefixis will be
grouped with 2 digit ones if they contain that 2 digit number. 
eg,

    [01]-red.tif  : group 01
    1[01]-red.tif : group 01

TODO: regex or something to tighten this up. This is also solved by
prepending 0 to the 2 digit files. E.g, by running

    rename 's/(^\d{2}-)/0$1/' *.tif

