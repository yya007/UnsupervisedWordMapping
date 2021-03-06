"""Code for constructing the model and get the outputs from the model."""
from __future__ import print_function
import tensorflow as tf
import layers

WORD_EMBED_DIM=300

# The number of samples per batch.
BATCH_SIZE = 100

POOL_SIZE = 50
ngf = 32
ndf = 64


def get_outputs(inputs, network="tensorflow", skip=False):
    word_a = inputs['word_a']
    word_b = inputs['word_b']

    fake_pool_a = inputs['fake_pool_a']
    fake_pool_b = inputs['fake_pool_b']

    with tf.variable_scope("Model") as scope:

        if network == "pytorch":
            current_discriminator = discriminator
            current_generator = build_generator_resnet_9blocks
        elif network == "tensorflow":
            current_discriminator = dis_tf
            current_generator = gen_tf

            # current_discriminator = discriminator_tf
            # current_generator = build_generator_resnet_9blocks_tf
        else:
            raise ValueError(
                'network must be either pytorch or tensorflow'
            )

        prob_real_a_is_real = current_discriminator(word_a, "d_A")
        prob_real_b_is_real = current_discriminator(word_b, "d_B")

        fake_word_b = current_generator(word_a, name="g_A", skip=skip)
        fake_word_a = current_generator(word_b, name="g_B", skip=skip)

        scope.reuse_variables()

        prob_fake_a_is_real = current_discriminator(fake_word_a, "d_A")
        prob_fake_b_is_real = current_discriminator(fake_word_b, "d_B")

        cycle_word_a = current_generator(fake_word_b, "g_B", skip=skip)
        cycle_word_b = current_generator(fake_word_a, "g_A", skip=skip)

        scope.reuse_variables()

        prob_fake_pool_a_is_real = current_discriminator(fake_pool_a, "d_A")
        prob_fake_pool_b_is_real = current_discriminator(fake_pool_b, "d_B")

    return {
        'prob_real_a_is_real': prob_real_a_is_real,
        'prob_real_b_is_real': prob_real_b_is_real,
        'prob_fake_a_is_real': prob_fake_a_is_real,
        'prob_fake_b_is_real': prob_fake_b_is_real,
        'prob_fake_pool_a_is_real': prob_fake_pool_a_is_real,
        'prob_fake_pool_b_is_real': prob_fake_pool_b_is_real,
        'cycle_word_a': cycle_word_a,
        'cycle_word_b': cycle_word_b,
        'fake_word_a': fake_word_a,
        'fake_word_b': fake_word_b,
    }

def gen_tf(inputgen, name="generator", skip=False):
    with tf.variable_scope(name):
        l1 = tf.layers.dense(inputgen,512)
        l2 = tf.layers.dense(l1,1024)
        l3 = tf.layers.dense(l2,2048)
        l4 = tf.layers.dense(l3,1024)
        l5 = tf.layers.dense(l4,512)
        out_gen = tf.layers.dense(l5,300)
        if skip is True:
            out_gen = tf.nn.tanh(inputgen + out_gen, "t1")
        else:
            out_gen = tf.nn.tanh(out_gen, "t1")
        return out_gen

def dis_tf(inputdisc, name="discriminator"):
    with tf.variable_scope(name):
        l1 = tf.layers.dense(inputdisc,512)
        l2 = tf.layers.dense(l1,300)
        l3 = tf.layers.dense(l2,256)
        l4 = tf.layers.dense(l3,128)
        l5 = tf.layers.dense(l4,64)
        l5 = tf.layers.dense(l4,32)
        l6 = tf.layers.dense(l5,2)
        out = tf.nn.softmax(l6)
    return out[:,0]



def build_resnet_block(inputres, dim, name="resnet", padding="REFLECT"):
    """build a single block of resnet.

    :param inputres: inputres
    :param dim: dim
    :param name: name
    :param padding: for tensorflow version use REFLECT; for pytorch version use
     CONSTANT
    :return: a single block of resnet.
    """
    with tf.variable_scope(name):
        out_res = tf.pad(inputres, [[0, 0], [1, 1], [
            1, 1], [0, 0]], padding)
        out_res = layers.general_conv2d(
            out_res, dim, 3, 3, 1, 1, 0.02, "VALID", "c1")
        out_res = tf.pad(out_res, [[0, 0], [1, 1], [1, 1], [0, 0]], padding)
        out_res = layers.general_conv2d(
            out_res, dim, 3, 3, 1, 1, 0.02, "VALID", "c2", do_relu=False)

        return tf.nn.relu(out_res + inputres)


def build_generator_resnet_9blocks_tf(inputgen, name="generator", skip=False):
    with tf.variable_scope(name):
        f = 7
        ks = 3
        padding = "REFLECT"

        pad_input = tf.pad(inputgen, [[0, 0], [ks, ks], [
            ks, ks], [0, 0]], padding)
        o_c1 = layers.general_conv2d(
            pad_input, ngf, f, f, 1, 1, 0.02, name="c1")
        o_c2 = layers.general_conv2d(
            o_c1, ngf * 2, ks, ks, 2, 2, 0.02, "SAME", "c2")
        o_c3 = layers.general_conv2d(
            o_c2, ngf * 4, ks, ks, 2, 2, 0.02, "SAME", "c3")

        o_r1 = build_resnet_block(o_c3, ngf * 4, "r1", padding)
        o_r2 = build_resnet_block(o_r1, ngf * 4, "r2", padding)
        o_r3 = build_resnet_block(o_r2, ngf * 4, "r3", padding)
        o_r4 = build_resnet_block(o_r3, ngf * 4, "r4", padding)
        o_r5 = build_resnet_block(o_r4, ngf * 4, "r5", padding)
        o_r6 = build_resnet_block(o_r5, ngf * 4, "r6", padding)
        o_r7 = build_resnet_block(o_r6, ngf * 4, "r7", padding)
        o_r8 = build_resnet_block(o_r7, ngf * 4, "r8", padding)
        o_r9 = build_resnet_block(o_r8, ngf * 4, "r9", padding)

        o_c4 = layers.general_deconv2d(
            o_r9, [BATCH_SIZE, 128, 128, ngf * 2], ngf * 2, ks, ks, 2, 2, 0.02,
            "SAME", "c4")
        o_c5 = layers.general_deconv2d(
            o_c4, [BATCH_SIZE, 256, 256, ngf], ngf, ks, ks, 2, 2, 0.02,
            "SAME", "c5")
        o_c6 = layers.general_conv2d(o_c5, IMG_CHANNELS, f, f, 1, 1,
                                     0.02, "SAME", "c6",
                                     do_norm=False, do_relu=False)

        if skip is True:
            out_gen = tf.nn.tanh(inputgen + o_c6, "t1")
        else:
            out_gen = tf.nn.tanh(o_c6, "t1")

        return out_gen


def build_generator_resnet_9blocks(inputgen, name="generator", skip=False):
    with tf.variable_scope(name):
        f = 7
        ks = 3
        padding = "CONSTANT"

        pad_input = tf.pad(inputgen, [[0, 0], [ks, ks], [
            ks, ks], [0, 0]], padding)
        o_c1 = layers.general_conv2d(
            pad_input, ngf, f, f, 1, 1, 0.02, name="c1")
        o_c2 = layers.general_conv2d(
            o_c1, ngf * 2, ks, ks, 2, 2, 0.02, "SAME", "c2")
        o_c3 = layers.general_conv2d(
            o_c2, ngf * 4, ks, ks, 2, 2, 0.02, "SAME", "c3")

        o_r1 = build_resnet_block(o_c3, ngf * 4, "r1", padding)
        o_r2 = build_resnet_block(o_r1, ngf * 4, "r2", padding)
        o_r3 = build_resnet_block(o_r2, ngf * 4, "r3", padding)
        o_r4 = build_resnet_block(o_r3, ngf * 4, "r4", padding)
        o_r5 = build_resnet_block(o_r4, ngf * 4, "r5", padding)
        o_r6 = build_resnet_block(o_r5, ngf * 4, "r6", padding)
        o_r7 = build_resnet_block(o_r6, ngf * 4, "r7", padding)
        o_r8 = build_resnet_block(o_r7, ngf * 4, "r8", padding)
        o_r9 = build_resnet_block(o_r8, ngf * 4, "r9", padding)

        o_c4 = layers.general_deconv2d(
            o_r9, [BATCH_SIZE, 128, 128, ngf * 2], ngf * 2, ks, ks, 2, 2, 0.02,
            "SAME", "c4")
        o_c5 = layers.general_deconv2d(
            o_c4, [BATCH_SIZE, 256, 256, ngf], ngf, ks, ks, 2, 2, 0.02,
            "SAME", "c5")
        o_c6 = layers.general_conv2d(o_c5, IMG_CHANNELS, f, f, 1, 1,
                                     0.02, "SAME", "c6",
                                     do_norm=False, do_relu=False)

        if skip is True:
            out_gen = tf.nn.tanh(inputgen + o_c6, "t1")
        else:
            out_gen = tf.nn.tanh(o_c6, "t1")

        return out_gen


def discriminator_tf(inputdisc, name="discriminator"):
    with tf.variable_scope(name):
        f = 4

        o_c1 = layers.general_conv2d(inputdisc, ndf, f, f, 2, 2,
                                     0.02, "SAME", "c1", do_norm=False,
                                     relufactor=0.2)
        o_c2 = layers.general_conv2d(o_c1, ndf * 2, f, f, 2, 2,
                                     0.02, "SAME", "c2", relufactor=0.2)
        o_c3 = layers.general_conv2d(o_c2, ndf * 4, f, f, 2, 2,
                                     0.02, "SAME", "c3", relufactor=0.2)
        o_c4 = layers.general_conv2d(o_c3, ndf * 8, f, f, 1, 1,
                                     0.02, "SAME", "c4", relufactor=0.2)
        o_c5 = layers.general_conv2d(
            o_c4, 1, f, f, 1, 1, 0.02,
            "SAME", "c5", do_norm=False, do_relu=False
        )

        return o_c5


def discriminator(inputdisc, name="discriminator"):
    with tf.variable_scope(name):
        f = 4

        padw = 2

        pad_input = tf.pad(inputdisc, [[0, 0], [padw, padw], [
            padw, padw], [0, 0]], "CONSTANT")
        o_c1 = layers.general_conv2d(pad_input, ndf, f, f, 2, 2,
                                     0.02, "VALID", "c1", do_norm=False,
                                     relufactor=0.2)

        pad_o_c1 = tf.pad(o_c1, [[0, 0], [padw, padw], [
            padw, padw], [0, 0]], "CONSTANT")
        o_c2 = layers.general_conv2d(pad_o_c1, ndf * 2, f, f, 2, 2,
                                     0.02, "VALID", "c2", relufactor=0.2)

        pad_o_c2 = tf.pad(o_c2, [[0, 0], [padw, padw], [
            padw, padw], [0, 0]], "CONSTANT")
        o_c3 = layers.general_conv2d(pad_o_c2, ndf * 4, f, f, 2, 2,
                                     0.02, "VALID", "c3", relufactor=0.2)

        pad_o_c3 = tf.pad(o_c3, [[0, 0], [padw, padw], [
            padw, padw], [0, 0]], "CONSTANT")
        o_c4 = layers.general_conv2d(pad_o_c3, ndf * 8, f, f, 1, 1,
                                     0.02, "VALID", "c4", relufactor=0.2)

        pad_o_c4 = tf.pad(o_c4, [[0, 0], [padw, padw], [
            padw, padw], [0, 0]], "CONSTANT")
        o_c5 = layers.general_conv2d(
            pad_o_c4, 1, f, f, 1, 1, 0.02, "VALID", "c5",
            do_norm=False, do_relu=False)

        return o_c5


def patch_discriminator(inputdisc, name="discriminator"):
    with tf.variable_scope(name):
        f = 4

        patch_input = tf.random_crop(inputdisc, [1, 70, 70, 3])
        o_c1 = layers.general_conv2d(patch_input, ndf, f, f, 2, 2,
                                     0.02, "SAME", "c1", do_norm="False",
                                     relufactor=0.2)
        o_c2 = layers.general_conv2d(o_c1, ndf * 2, f, f, 2, 2,
                                     0.02, "SAME", "c2", relufactor=0.2)
        o_c3 = layers.general_conv2d(o_c2, ndf * 4, f, f, 2, 2,
                                     0.02, "SAME", "c3", relufactor=0.2)
        o_c4 = layers.general_conv2d(o_c3, ndf * 8, f, f, 2, 2,
                                     0.02, "SAME", "c4", relufactor=0.2)
        o_c5 = layers.general_conv2d(
            o_c4, 1, f, f, 1, 1, 0.02, "SAME", "c5", do_norm=False,
            do_relu=False)

        return o_c5
