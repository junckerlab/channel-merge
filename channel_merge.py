#!/usr/bin/env python2
# -*- coding: utf-8 -*-
""" 
Merge greyscale single channel (r,g,b) tiffs into one rgb composite while
applying a simple correction for uneven illumination. 

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

Assumes the following file naming conventions:
    <two digit id>-<channel_name><optional '-2/3/etc'>.tif
    e.g.,
        01-red.tif
        23-blue-2.tif    # an alternative blue channel scan of img 23
    
    Whitespace will be replaced with '-'. This *could* overwrite data if you
    had two files with identical names sans ' ' and '-'. 
    e.g., 
        01 red 3.tif >> 01-red-3.tif
        01 red-3.tif >> 01-red-3.tif    # will clobber the file above

Spelling Errors:
    The first letter of a file's channel_name is taken to imply it's color.
    e.g.,
        01-reed.tif        # red
        44-guleinoiena.tif # green
        10-b.tif           # blue
        10-bfue.tif        # excluded (see Brightfield Exclusion below)

Brightfield Exclusion: 
    Any .tif with a channel_name *starting with* 'bf' is assumed to be a bright
    field image and is excluded from any merges. So as long as blue channels
    are not named bf* things should be okay.
    e.g.,
        01-bf.tif, 01-bf-2.tif, 01-bf_actuallybluetrustme.tif # excluded
        01-bl.tif, 01-blbfue.tif                              # blue

Terminology (for variable names):
    chanel : one .tif file, red, green, blue, or bf (bright field)
        e.g., '01-red.tif'
    image : an area of the plate that is imaged, multiple channels correspond
        to one image. e.g., '01-*.tif'
    plate/sample : one sample of cells being imaged, a folder of images
"""

from __future__ import division
import numpy as np
import os
from glob import glob
import itertools
import argparse
import sys
import scipy.ndimage as ndi
import cv2
from libtiff import TIFF

### Script Info
__author__ = 'Nick Chahley, https://github.com/nickchahley'
__version__ = '0.2.2'
__day__ = '2018-06-25'

### Command line flags/options
def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument('-p', '--defdir', type=str, help='Def dir for Path dialog')
    parser.add_argument('-s', '--sigma', type=float, default=50., 
                        help='Sigma value for gaussian blur during illumination \
                        correction. Note: the useable range for this value is \
                        greatly dependent on the image set. Best to experiment.')
    parser.add_argument('-d', '--outdir', type=str, help='Name of dir to output \
                        merged images to. Created if DNE.', default='merged_corrected') 
    parser.add_argument('-n', '--nopop', action='store_true', dest='no_popup',
                        help='Supress "Run Complete" popup message. Useful for \
                        batch running, since otherwise the message must be closed \
                        by user input before the script exits.')
    parser.add_argument('--path', type=str, help='skip gui and use this path')
    # possible future: preprocess on/off 
    args = parser.parse_args()
    if args.path:
        args.no_popup = True 
    return args


### Function Defs
def popup_message(text = '', title='Message'):
    try:
        # Python 3.x imports
        import tkinter as tk
        from tkinter import messagebox
    except ImportError:
        # Fall back to 2.x
        import Tkinter as tk
        import tkMessageBox as messagebox

    root = tk.Tk().withdraw()  # hide the root window

    messagebox.showinfo(title, text)  # show the messagebo
def path_dialog(whatyouwant):
    """ 
    Prompt user to select a dir (def) or file, return its path

    In
    ---
    whatyouwant : str opts=['folder', 'file']

    Out
    ---
    path : str, Absolute path to file

    """
    import Tkinter
    # TODO allow multiple (shift-click) dir selections?
    root = Tkinter.Tk()
    root.withdraw()

    opt = {}
    opt['parent'] = root

    # opt['initialdir'] = './'
    opt['initialdir'] = args.defdir if args.defdir else './'


    if whatyouwant == 'folder':
        from tkFileDialog import askdirectory
        ask_fun = askdirectory
        # dirpath will be to dir that user IS IN when they click confirm
        opt['title'] = 'Select directory containing images to merge (be IN this folder)'

    if whatyouwant == 'file':
        from tkFileDialog import askopenfilename
        ask_fun = askopenfilename
        # opt['title'] = 'Select psd file to detect peaks from'
        # opt['filetypes'] = (('CSV files', '*.csv'), ('All files', '*.*'))

    path = ask_fun(**opt)

    # Quit if user doesn't select anything
    # No idea why an unset path is of type tuple
    if type(path) == tuple:
        m = 'No path selected, exiting'
        popup_message(m)
        sys.exit(m)

    return path
def cleanup_filenames(filenames):
    """ 
    replace whitespace and exclude bright field tiff files
    """
    def rename(filenames):
        def format_filenames(filenames):
            def format_trailing_nums(s):
                import re

                # trim .extension
                sp = '.'.join(s.split('.')[:-1])

                # match digits at end of string
                m = re.search('\d+$', sp)
                if not m:
                    # string does not end in num
                    new = s
                else:
                    # string ends in num
                    endnum = m.group()
                    new = endnum.join(sp.split(endnum)[:-1])
                    if new[-1] == '-':
                        # Trailing '-', rm to avoid getting '01-blue--2.tif'
                        new = new[:-1]
                    ext = '.' + s.split('.')[-1]
                    new = '-'.join((new, endnum)) + ext

                # correct no seperator following prefix digits
                # if I was good at regex this would take like zero lines
                pfx = new.split('-')[0]
                if not pfx.isdigit():
                    m = re.search('^\d+', pfx)
                    if m:
                        mid = pfx.replace(m.group(), '')
                        end = '-'.join(new.split('-')[1:])
                        new = '-'.join((m.group(), mid, end))

                return new
            # replace whitespace
            filenames = ['-'.join(f.split()) for f in filenames]

            # ensure trailing digits are separated from channel_name w/ '-'
            filenames = [format_trailing_nums(f) for f in filenames]
            return filenames
        for old, new in zip(filenames, format_filenames(filenames)):
            os.rename(old, new)
    rename(filenames)
    filenames = [f for f in filenames if '-bf' not in f]
    filenames.sort()
    return filenames
def group_images(filenames):
    """ 
    Return a dict containing image numbers as keys and a list of their
    associated filenames as values. 
    
    Issue: Numeric prefix was assumed to be always two digits, which is not
    the case. The `n+'-'` is too general and files w/ 3 digit prefixis will be
    grouped with 2 digit ones if they contain that 2 digit number. 
    eg,
        [01]-red.tif  : group 01
        1[01]-red.tif : group 01
    TODO: regex or something to tighten this up. This is also solved by
    prepending 0 to the 2 digit files, 
        rename 's/(^\d{2}-)/0$1/' *.tif

    filenames : list
    ret channels : dict

    Naming conventions (assumed):
        <dd>-<color[text]>.tif : for 1st scans "norm"
        <dd>-<color[text]>-<d>.tif : for 2nd+ scans "extra"
    """
    # Get one list item for each unique image number
    nums = [f.split('-')[0] for f in filenames]
    nums = sorted(set(nums)) # rm repeats and back to sorted list
    
    # Make dict of img num and channel files
    channels = [] 
    for n in nums:
        channels.append([f for f in filenames if n+'-' in f])
    channels.sort()
    channels = dict(zip(nums, channels))

    return channels
def channel_combos(files):
    """ 
    Infer channel colors from names and return a dict with the names of all
    files for each color

    In
    ---
    files : list of strings

    Out
    ---
    combos : list of tuples, each tuple is one combo of rgb channels sorted
        in order of (r,g,b). Imagemagick will expect this order.
    """
    colors = {'r' : [],
              'g' : [],
              'b' : []}

    # interrogate channel color from filename: look at first letter 
    # and assume r* = red, etc
    for f in files:
        # get the first letter of word following the img num prefix ('\d*-')
        c = f.split('-')[1].lower()[0]
        if c is 'r':
            colors['r'].append(f)
        elif c is 'g':
            colors['g'].append(f)
        elif c is 'b':
            colors['b'].append(f)

    # choose one item from each list, making all possible combos
    combos = [p for p in itertools.product(*colors.values())]

    # reverse alpha sort each tuple so that order is rgb -- imagemagick assumes
    # this order
    combos = [sorted(t, reverse=True) for t in combos]

    # List of tuples, each tuple is one combo of rgb channels
    return combos
def tiffs_iterate_combos(d):
    """ 
    Ret dict with key for each image number make all possible rgb combinations. 

    In
    ---
    d : dict of dicts of lists
        d = { <##> : { 
            r : [filenames], g : [], b : [] } 
            }

    Out
    ---
    imgs : dict of lists of tuples. Each tuple is one rgb combination. Each 
        list is all tuples for a given image number.
    """
    imgs = {}
    for k, v in d.iteritems():
        imgs[k] = channel_combos(v)
    
    # dict of list of tuples
    return imgs

## Resturaunt Nouveau System
def preproc_imgs(imgs, sigma, oudtdir='preproc'):
    """ 
    Hastily commented preprocessing. 'uids' is a dumb name for this dict.

    imgs : dict w/ image numbers as keys 
    """
    def get_uids(imgs):
        # Get a unique id for each distinct len3 list of r,g,b files
        uids = {}
        for k, imls in imgs.iteritems():
            if len(imls) == 1:
                if type(imls[0]) is list:
                    # then we have a len1 list containing another list for some reason
                    # flatten it
                    uids[k] = imls[0]
                else:
                    uids[k] = imls

            if len(imls) > 1:
                # we have multiple rgb combos, append nums >1 to num/uid
                uids[k] = imls[0]
                for i in range(1,len(imls)):
                    uid = '-'.join((k, str(i+1)))
                    uids[uid] = imls[i]
        return uids
    def illum_correction(x, sigma, method='subtract'):
        """ 
        Gaussian blurr background subtraction.

        Aim is to smooth image until it is devoid of features, but retains the
        weighted average intensity across the image that corresponds to the
        underlying illumination pattern. Then subtract

        This correction is only aware of the single image/channel that it is fed.
        It might be a better idea to try and implement illumination correction
        using multiple channels/images taken from the same experiment.
        """
        y = ndi.gaussian_filter(x, sigma=sigma, mode='constant', cval=0)
        if method == 'subtract':
            return cv2.subtract(x, y)
        elif method == 'divide':
            return cv2.divide(x, y)
        else:
            raise ValueError("Unsupported method: %s" %method)

    uids = get_uids(imgs)
    # For each set of 3 channel filenames, read each image, preform
    # illumination correction, and stack them together into an rgb image.
    rgb = {}
    for uid, imls in uids.iteritems():

        # List of greyscale channel ims : r,g,b
        ims = [tiffread(f) for f in imls] 

        # Guassian blur bg subtraction for each channel
        ims_corr = [illum_correction(x, sigma) for x in ims]

        try:
            rgb[uid] = np.dstack(ims_corr)
        except ValueError as e:
            print('Skipping image # %s. Channels have non uniform shape? %s' 
                  % (uid, e))
            print('R: %s' % str(ims_corr[0].shape))
            print('G: %s' % str(ims_corr[1].shape))
            print('B: %s' % str(ims_corr[2].shape))
    
    return rgb
def outfile_names(rgb, suffix='rgb', ext='.tif'):
    """ Take dict of num : rgb im and return outfilename : rgb num
    """

    for k in rgb.keys():
        ks = k.split('-')
        # if im num is of fmt '01-2' make name '01-suffix-2.ext'
        if len(ks) == 2:
            fname = '-'.join((ks[0], suffix, ks[-1])) + ext
        else:
            fname = '-'.join((k, suffix)) + ext
        rgb[fname] = rgb.pop(k)
    return rgb
def tiffread(f):
    """
    Return a single array if given a filename, and a rgb stack if fed a len 3
    list of filenames.

    f : str or list (len 3), filename(s) to be read.

    ret : 2d or 3d ndarray
    """
    if type(f) is str:
        # single image
        tif = TIFF.open(f, mode='r')
        return tif.read_image()

    elif type(f) is list and len(f) == 3:
        # return rgb stack
        f.sort(reverse=True) # so r, g, b
        tif = [TIFF.open(x, mode='r') for x in f]
        ims = [t.read_image() for t in tif]
        return np.dstack(ims)
    else:
        raise ValueError("f must be a string or list of 3 strings")
def tiffwrite(filename, im):
    tif = TIFF.open(filename, mode='w')
    # Write as a composite r,g,b if it looks like one
    if len(im.shape) == 3 and im.shape[-1] == 3:
        tif.write_image(im, write_rgb = True)
    else:
        tif.write_image(im)


### Main 
def main():
    if args.path:
        path = args.path
        rootpath = os.getcwd()
    else:
        path = path_dialog(whatyouwant = 'folder')
    os.chdir(path)

    # Filename String Manipulations
    filenames = cleanup_filenames(glob("*.tif"))
    channels = group_images(filenames)

    # Image Processing
    print('Processing images...')
    imgs = tiffs_iterate_combos(channels)
    rgb = preproc_imgs(imgs, sigma = args.sigma)
    rgb = outfile_names(rgb)

    # Make output dir if it does not exist
    print('Writing images to %s' % args.outdir)
    if not os.path.exists(args.outdir):
        os.makedirs(args.outdir)
    
    for fname, im in rgb.iteritems():
        tiffwrite('/'.join((args.outdir, fname)), im)

    if args.path:
        # go back to root as to not mess up next script exec
        os.chdir(rootpath)

    # FREEDOM


# run the main function
if __name__ == '__main__':
    args = parse_args()
    main()
    if args.no_popup == False:
        popup_message('Run complete')
