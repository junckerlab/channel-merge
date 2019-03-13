#!/usr/bin/env python3

import numpy as np
import os
from glob import glob
import itertools
import argparse
import sys
import scipy.ndimage as ndi
import cv2
import tifffile as tf 
import tkinter as tk
from tkinter import messagebox
from tkinter.filedialog import askopenfilename
from tkinter.filedialog import askdirectory

# Script Info
__author__  = 'Nick Chahley, https://github.com/nickchahley'
__url__     = 'https://github.com/junckerlab/channel_merge'
__version__ = '1.0'
__day__     = '2019-03-12'


def main(args):
    """ args: argparse arguments
    """
    if args.path:
        path = args.path
        rootpath = os.getcwd()
    else:
        path = path_dialog(whatyouwant = 'folder')
    os.chdir(path)

    # Filename String Manipulations
    print('Formatting filenames...')
    filenames = cleanup_filenames(glob("*.tif"))
    channels = group_images(filenames)
    imgs = tiffs_iterate_combos(channels)

    # Image Processing
    print('Processing images...')
    rgb = preproc_imgs(imgs, sigma = args.sigma)
    rgb = outfile_names(rgb)

    # Make output dir if it does not exist
    print('Writing images to %s' % args.outdir)
    if not os.path.exists(args.outdir):
        os.makedirs(args.outdir)
    
    # Write the rgb stacks to files in output dir
    for fname, im in rgb.items():
        tiffwrite('/'.join((args.outdir, fname)), im)

    if args.path:
        # go back to root as to not mess up next script exec
        os.chdir(rootpath)

    # FREEDOM


def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument('-p', '--defdir', type=str, 
                        help='Open the path dialog in this dir')
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
    parser.add_argument('--path', type=str, 
                        help='skip gui and load ims from this dir')
    # possible future: preprocess on/off 
    args = parser.parse_args()
    if args.path:
        args.no_popup = True 
    return args

def popup_message(text = '', title='Message'):
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
    # TODO allow multiple (shift-click) dir selections
    root = tk.Tk()
    root.withdraw()

    opt = {}
    opt['parent'] = root

    opt['initialdir'] = args.defdir if args.defdir else './'


    if whatyouwant == 'folder':
        ask_fun = askdirectory
        # dirpath will be to dir that user IS IN when they click confirm
        opt['title'] = 'Select directory containing images to merge (be IN this folder)'

    if whatyouwant == 'file':
        ask_fun = askopenfilename

    path = ask_fun(**opt)

    # Quit if user doesn't select anything
    # No idea why an unset path is of type tuple
    if type(path) == tuple:
        m = 'No path selected, exiting'
        popup_message(m)
        sys.exit(m)

    return path

def cleanup_filenames(filenames):
    """ replace whitespace and exclude bright field tiff files """

    def safe_rename(old, new):
        if os.path.exists(new):
            # Skip to avoid clobbering new. If this breaks the script it will
            # be caught 
            return
        else:
            os.rename(old, new)

    def format_filenames(filenames):

        def format_trailing_nums(s):
            import re

            # trim .extension
            sp = '.'.join(s.split('.')[:-1])

            # match digits at end of string
            m = re.search('\d+$', sp)
            if not m:
                # string does not end in num, ex. '01-blue.tif'
                new = s
            else:
                # string ends in num, ex. '01-blue-2.tif'
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

    # Rename the files to be compliant with the format <id>-channel[-num].tif
    fmt_filenames = format_filenames(filenames)
    for old, new in zip(filenames, fmt_filenames):
        safe_rename(old, new)


    # Exclude brightfield files from downstream processing
    fmt_filenames = [f for f in fmt_filenames if '-bf' not in f]
    fmt_filenames.sort()
    return fmt_filenames

def group_images(filenames):
    """ 
    Return a dict containing image numbers as keys and a list of their
    associated filenames as values. 
    
    2018-08-28
    Should now not include files like 101-red.tif in group 01.
    
    filenames : list
    ret channels : dict

    Naming conventions (assumed):
        <dd>-<color[text]>.tif : for 1st scans "norm"
        <dd>-<color[text]>-<d>.tif : for 2nd+ scans "extra"
    """
    nums = [f.split('-')[0] for f in filenames]
    nums = sorted(set(nums)) # rm repeats and back to sorted list
    

    # Make dict of img num and channel files
    channels = [] 
    for n in nums:
        channels.append([f for f in filenames if n == f.split('-')[0]])
    channels.sort()
    channels = dict(zip(nums, channels))

    return channels

def tiffs_iterate_combos(channels):
    """ Ret dict with key for each image number make all possible rgb
    combinations. 

    In
    ---
    channels : dict of dicts of lists
        { <id> : 
            { r : [filenames], g : [], b : [] } 
        }
    ^ no that's wrong. I'm actually feeding it:
        { <id> : [<filenames>] }

    Out
    ---
    imgs : dict of lists of tuples. Each tuple is one rgb combination. Each 
        list is all tuples for a given image number.
    """

    imgs = {}
    bad_files = []
    for im_id, filenames in channels.items():

        colors = {'r' : [],
                  'g' : [],
                  'b' : []}

        # interrogate channel color from filename: look at first letter 
        # and assume r* = red, etc
        for f in filenames:
            try:
                # get the first letter of word following the img num prefix ('\d*-')
                c = f.split('-')[1].lower()[0]
                if c is 'r':
                    colors['r'].append(f)
                elif c is 'g':
                    colors['g'].append(f)
                elif c is 'b':
                    colors['b'].append(f)
            except IndexError as e:
                bad_files.append(f)

        # choose one item from each list, making all possible combos
        combos = [p for p in itertools.product(*colors.values())]

        # reverse alpha sort each tuple so that order is rgb 
        combos = [sorted(t, reverse=True) for t in combos]

        imgs[im_id] = combos 


    # bad_files is an exit flag is so that if multiple uninferable colors
    # exist, all of them are printed, and the user doesn't end up fixing a
    # conflict only to run it again and find there was a second, previously
    # unreported conflict they now need to go back and resolve.
    if len(bad_files) > 0:
        msg = (
            bcolors.WARNING + 'Error: ' + bcolors.ENDC +
            'Unable to infer color channel from {n} filename(s)\n'
            'This is likely due to the filename not containing any '
            '"-" separators from a conflict when trying to coerce the '
            'image names to the format "<id>-channel[-opt]". You will '
            'need to manually resolve any name conflicts.').format(
                n=len(bad_files))
        sys.exit(msg + bcolors.FAIL 
                 + "\nAborting script due to uninferable color channels")
        # sys.exit(msg + "\nAborting script due to uninferable color channels")
    
    # dict( list( tuple ) )
    return imgs

def preproc_imgs(imgs, sigma, oudtdir='preproc', mode='nearest'):
    """ 
    Hastily commented preprocessing. 'uids' is a dumb name for this dict.

    imgs : dict w/ image numbers as keys 
    """
    def get_uids(imgs):
        # Get a unique id for each distinct len3 list of r,g,b files
        uids = {}
        for k, imls in imgs.items():
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
    def illum_correction(x, sigma, mode='nearest', method='subtract'):
        """ 
        Gaussian blurr background subtraction.

        Aim is to smooth image until it is devoid of features, but retains the
        weighted average intensity across the image that corresponds to the
        underlying illumination pattern. Then subtract

        This correction is only aware of the single image/channel that it is fed.
        It might be a better idea to try and implement illumination correction
        using multiple channels/images taken from the same experiment.
        """
        y = ndi.gaussian_filter(x, sigma=sigma, mode=mode, cval=0)
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
    for uid, imls in uids.items():

        # List of greyscale channel ims : r,g,b
        ims = [tiffread(f) for f in imls]

        # Guassian blur bg subtraction for each channel
        ims_corr = [illum_correction(x, sigma, mode) for x in ims]

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
    outfile_rgb = {}
    for im_id, data in rgb.items():
        ks = im_id.split('-')
        # if im num is of fmt '01-2' make name '01-suffix-2.ext'
        if len(ks) == 2:
            fname = '-'.join((ks[0], suffix, ks[-1])) + ext
        else:
            fname = '-'.join((im_id, suffix)) + ext
        outfile_rgb[fname] = data
    return outfile_rgb

def tiffread(f):
    """ Read .tiff into numpy.ndarray
    Might be simpler than w/ libtiff. I'll note the catches I used to need 
    w/ libtiff just in case:
        - if reading a list, read a list of gs tifs and np.dstack (will do
        similar here)

    In
    --
    f : str or list, filename if gs or rgb, filenames if list of gs

    Out
    ---
    im : numpy.ndarray
    """
    try:
        if type(f) is str:
            # single image
            im = tf.imread(f)
            return im

        elif type(f) is list and len(f) == 3:
            # return rgb stack
            f.sort(reverse=True) # so r, g, b
            ims = [tf.imread(x) for x in f]
            return np.dstack(ims)
        else:
            raise ValueError("f must be a string or list of 3 strings")
    except tf.tifffile.TiffFileError:
        sys.exit(bcolors.FAIL+'ERROR: %s is not a tiff file. Exiting' %f)

def tiffwrite(filename, im):
    """ Write numpy.ndarray to tif.
    Might be simpler than w/ libtiff. I'll note the catches I used to need 
    w/ libtiff just in case:
        - need to distinguish b/t greyscale and rgb (write_rgb=True if shape 3)

    filename : str
    im : numpy.ndarray
    """
    tf.imwrite(filename, im)

class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

if __name__ == '__main__':
    args = parse_args()
    main(args)
    if args.no_popup == False:
        popup_message('Run complete')

