"""Script for higher-level statistical analysis.

Usage:
    get_probs.py (--cfg-path=<p>) [--debug]
    get_probs.py -h | --help

Options:
    -h --help       Show this screen.
    --cfg-path=<p>  Config path.
    --debug         Run in debug mode.

"""

from __future__ import print_function

import os

from docopt import docopt

import numpy as np
import tensorflow as tf

from models.baseline_smaller import BaselineSmallerModel
from utils.config import Config

def get_probs(cfg_path, debug):

    config = Config(cfg_path)
    
    ckpt_path = config.ckpt_path
    res_path = config.res_path
    
    model = BaselineSmallerModel(config)

    train_ex_paths = model.train_ex_paths
    val_ex_paths = model.val_ex_paths
    if debug:
        train_ex_paths = train_ex_paths[:2]
        val_ex_paths = val_ex_paths[:2]

    saver = tf.train.Saver()

    with tf.Session() as sess:

        saver.restore(sess, ckpt_path)

        print('\nget probs\n')
        fprobs = []
        for ex, ex_path in enumerate(val_ex_paths):
            print(ex)
            _, _, fprob, _ = model._segment(ex_path, sess)
            fprobs.append(fprob)

        fprobs = np.array(fprobs)

        np.savez(res_path,
                 fprobs=fprobs,
                 val_ex_paths=val_ex_paths)

if __name__ == '__main__':
    arguments = docopt(__doc__)
    get_probs(arguments['--cfg-path'], arguments['--debug'])