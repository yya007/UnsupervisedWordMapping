# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.
#

import os
import time

from logging import getLogger
import scipy
import scipy.linalg
import torch
from torch.autograd import Variable
from torch.nn import functional as F

from .utils import get_optimizer, export_embeddings
from .utils import clip_parameters
from .dico_builder import build_dictionary
from .evaluation.word_translation import DIC_EVAL_PATH, load_identical_char_dico, load_dictionary, get_word_translation_accuracy, get_word_translation_accuracy_score

logger = getLogger()

class Trainer_Cycle(object):

    # mapping is actually a single layer generator
    def __init__(self, src_emb, tgt_emb, mapping1,mapping2,discriminator1,discriminator2, params):
        """
        Initialize trainer script.
        """
        self.src_emb = src_emb
        self.tgt_emb = tgt_emb
        self.src_dico = params.src_dico
        # print (self.src_dico)
        self.tgt_dico = getattr(params, 'tgt_dico', None)
        # print (self.tgt_dico)
        self.mapping1 = mapping1
        self.mapping2 = mapping2
        self.discriminator1 = discriminator1
        self.discriminator2 = discriminator2
        self.params = params

        # optimizers
        if hasattr(params, 'map_optimizer'):
            optim_fn1, optim_params1 = get_optimizer(params.map_optimizer)
            self.map_optimizer1 = optim_fn1(mapping1.parameters(), **optim_params1)
            optim_fn2, optim_params2 = get_optimizer(params.map_optimizer)
            self.map_optimizer2 = optim_fn2(mapping2.parameters(), **optim_params2)
        if hasattr(params, 'dis_optimizer'):
            optim_fn1, optim_params1 = get_optimizer(params.dis_optimizer)
            self.dis_optimizer1 = optim_fn1(discriminator1.parameters(), **optim_params1)
            optim_fn2, optim_params2 = get_optimizer(params.dis_optimizer)
            self.dis_optimizer2 = optim_fn2(discriminator2.parameters(), **optim_params2)
        else:
            assert discriminator1 is None
            assert discriminator2 is None

        # best validation score
        self.best_valid_metric = -1e12

        self.decrease_lr = False

    def cycle_lambda(self, direction):
        if direction:
            return self.params.lambda_a
        return self.params.lambda_b

    def discriminator(self, direction):
        if direction:
            # print('using dis1')
            return self.discriminator1
        # print('using dis2')
        return self.discriminator2

    def mapping(self, direction):
        if direction:
            # print('using map1')
            return self.mapping1;
        # print('using map2')
        return self.mapping2

    def map_optimizer(self, direction):
        if direction:
            return self.map_optimizer1;
        return self.map_optimizer2

    def dis_optimizer(self, direction):
        if direction:
            return self.dis_optimizer1;
        return self.dis_optimizer2


    def get_dis_xy(self, volatile, direction):
        """
        Get discriminator input batch / output target.
        """
        # select random word IDs
        bs = self.params.batch_size
        mf = self.params.dis_most_frequent
        assert mf <= min(len(self.src_dico), len(self.tgt_dico))
        src_ids = torch.LongTensor(bs).random_(len(self.src_dico) if mf == 0 else mf)
        tgt_ids = torch.LongTensor(bs).random_(len(self.tgt_dico) if mf == 0 else mf)
        if self.params.cuda:
            src_ids = src_ids.cuda()
            tgt_ids = tgt_ids.cuda()
        # get word embeddings
        src_emb = self.src_emb(Variable(src_ids, volatile=True))
        tgt_emb = self.tgt_emb(Variable(tgt_ids, volatile=True))

        if direction:
            src_emb = self.mapping(direction)(Variable(src_emb.data, volatile=volatile))
            tgt_emb = Variable(tgt_emb.data, volatile=volatile)
            x = torch.cat([src_emb, tgt_emb], 0)
        else:
            src_emb = Variable(src_emb.data, volatile=volatile)
            tgt_emb = self.mapping(direction)(Variable(tgt_emb.data, volatile=volatile))
            x = torch.cat([tgt_emb, src_emb], 0)

        # input / target
       
        y = torch.FloatTensor(2 * bs).zero_()
        y[:bs] = 1 - self.params.dis_smooth
        y[bs:] = self.params.dis_smooth
        y = Variable(y.cuda() if self.params.cuda else y)

        return x, y

    def dis_step(self, stats, direction):
        # if direction:
        #     print("----dis normal")
        # else:
        #     print("----dis reverse")
        """
        Train the discriminator.
        """
        self.discriminator(direction).train()

        # loss
        x, y = self.get_dis_xy(volatile=True, direction=direction)
        preds = self.discriminator(direction)(Variable(x.data))
        loss = F.binary_cross_entropy(preds, y)

        if direction:
            stats['DIS_A_COSTS'].append(loss.data[0])
        else:
            stats['DIS_B_COSTS'].append(loss.data[0])

        # check NaN
        if (loss != loss).data.any():
            logger.error("NaN detected (discriminator)")
            exit()

        # optim
        self.dis_optimizer(direction).zero_grad()
        loss.backward()
        self.dis_optimizer(direction).step()
        clip_parameters(self.discriminator(direction), self.params.dis_clip_weights)

    def mapping_step(self, stats, direction):
        """
        Fooling discriminator training step.
        """
        if self.params.dis_lambda == 0:
            return 0

        self.discriminator(direction).eval()

        # loss
        x, y = self.get_dis_xy(volatile=False, direction=direction)
        preds = self.discriminator(direction)(x)
        
        map_loss = F.binary_cross_entropy(preds, 1 - y)
        cycle_A_loss=self.consistency_loss(volatile=False, direction=True)
        cycle_B_loss=self.consistency_loss(volatile=False, direction=False)

        if direction:
            stats['GAN_A_COSTS'].append(map_loss.data[0])
        else:
            stats['GAN_B_COSTS'].append(map_loss.data[0])

        stats['CYC_A_COSTS'].append(cycle_A_loss.data[0])
        stats['CYC_B_COSTS'].append(cycle_B_loss.data[0])
        # print(map_loss)
        loss = self.params.dis_lambda * map_loss + self.cycle_lambda(True) * cycle_A_loss + self.cycle_lambda(False) * cycle_B_loss
        
        # print(loss)
        # check NaN
        if (loss != loss).data.any():
            logger.error("NaN detected (fool discriminator)")
            exit()

        # optim
        self.map_optimizer(direction).zero_grad()
        loss.backward()
        self.map_optimizer(direction).step()
        self.orthogonalize(direction)


    def consistency_loss(self, volatile, direction):
        bs = 2*self.params.batch_size
        mf = self.params.dis_most_frequent
        assert mf <= min(len(self.src_dico), len(self.tgt_dico))

        if direction:
            dico=self.src_dico
            emb=self.src_emb
        else:
            dico=self.tgt_dico
            emb=self.tgt_emb
        
        ids = torch.LongTensor(bs).random_(len(dico) if mf == 0 else mf)
        
        if self.params.cuda:
            ids = ids.cuda()

        emb_part = Variable(emb(Variable(ids, volatile=True)).data, volatile=volatile)
        
        if self.params.cc_method=='default':
            emb_part_cycle = self.mapping(not direction)(self.mapping(direction)(emb_part))
            loss = F.l1_loss(emb_part,emb_part_cycle)

        else:
            tgt_emb = emb.weight.data
            src_emb = self.mapping(not direction)(self.mapping(direction)(emb.weight)).data
            if self.params.cuda:
                tgt_emb = tgt_emb.cuda()
                src_emb = src_emb.cuda()


            dico = torch.LongTensor(bs, 2)
            dico[:, 0] = ids
            dico[:, 1] = ids

            if self.params.cuda:
                dico = dico.cuda()
            
            t1=time.time()
            scores = get_word_translation_accuracy_score(dico, src_emb, tgt_emb, method=self.params.cc_method)
            t2=time.time()


            # indices = scores.topk(1, 1, True)[1][:,0]
            indices = scores.max(1)[1]
            t3=time.time()

            print(t2-t1,t3-t2)
            emb_part_cycle = Variable(emb(Variable(indices, volatile=True)).data, volatile=volatile)
            loss = F.l1_loss(emb_part,emb_part_cycle)

            

            # y = torch.FloatTensor(bs).zero_()
            # y[:] = 0
            # results = []
            # top_matches = scores.topk(100, 1, True)[1]
            # for k in [1]:
            #     top_k_matches = top_matches[:, :k]
            #     _matching = (top_k_matches == dico[:, 1][:, None].expand_as(top_k_matches)).sum(1)
            #     # allow for multiple possible translations
            #     matching = {}
            #     for i, src_id in enumerate(dico[:, 0]):
            #         matching[src_id] = min(matching.get(src_id, 0) + _matching[i], 1)
            #     # evaluate precision@k
            #     precision_at_k = list(matching.values())
            #     loss = F.l1_loss(y,precision_at_k)

        return loss

    def load_training_dico(self, dico_train):
        """
        Load training dictionary.
        """
        word2id1 = self.src_dico.word2id
        word2id2 = self.tgt_dico.word2id

        # identical character strings
        if dico_train == "identical_char":
            self.dico = load_identical_char_dico(word2id1, word2id2)
        # use one of the provided dictionary
        elif dico_train == "default":
            filename = '%s-%s.0-5000.txt' % (self.params.src_lang, self.params.tgt_lang)
            self.dico = load_dictionary(
                os.path.join(DIC_EVAL_PATH, filename),
                word2id1, word2id2
            )
        # dictionary provided by the user
        else:
            self.dico = load_dictionary(dico_train, word2id1, word2id2)

        # cuda
        if self.params.cuda:
            self.dico = self.dico.cuda()

    def build_dictionary(self, direction):
        """
        Build a dictionary from aligned embeddings.
        """
        if direction:
            src_emb = self.mapping(direction)(self.src_emb.weight).data
            tgt_emb = self.tgt_emb.weight.data
        else:
            src_emb = self.src_emb.weight.data
            tgt_emb = self.mapping(direction)(self.tgt_emb.weight).data

        src_emb = src_emb / src_emb.norm(2, 1, keepdim=True).expand_as(src_emb)
        tgt_emb = tgt_emb / tgt_emb.norm(2, 1, keepdim=True).expand_as(tgt_emb)
        self.dico = build_dictionary(src_emb, tgt_emb, self.params)

    def procrustes(self, direction):
        """
        Find the best orthogonal matrix mapping using the Orthogonal Procrustes problem
        https://en.wikipedia.org/wiki/Orthogonal_Procrustes_problem
        """
        if direction:
            A = self.src_emb.weight.data[self.dico[:, 0]]
            B = self.tgt_emb.weight.data[self.dico[:, 1]]
        else:
            B = self.src_emb.weight.data[self.dico[:, 0]]
            A = self.tgt_emb.weight.data[self.dico[:, 1]]
        W = self.mapping(direction).weight.data
        M = B.transpose(0, 1).mm(A).cpu().numpy()
        U, S, V_t = scipy.linalg.svd(M, full_matrices=True)
        W.copy_(torch.from_numpy(U.dot(V_t)).type_as(W))

    def orthogonalize(self, direction):
        """
        Orthogonalize the mapping.
        """
        if self.params.map_beta > 0:
            W = self.mapping(direction).weight.data
            beta = self.params.map_beta
            W.copy_((1 + beta) * W - beta * W.mm(W.transpose(0, 1).mm(W)))

    def update_lr(self, to_log, metric):
        """
        Update learning rate when using SGD.
        """
        if 'sgd' not in self.params.map_optimizer:
            return
        old_lr = self.map_optimizer(True).param_groups[0]['lr']
        new_lr = max(self.params.min_lr, old_lr * self.params.lr_decay)
        if new_lr < old_lr:
            logger.info("Decreasing normal direction learning rate: %.8f -> %.8f" % (old_lr, new_lr))
            self.map_optimizer(True).param_groups[0]['lr'] = new_lr

        old_lr = self.map_optimizer(False).param_groups[0]['lr']
        new_lr = max(self.params.min_lr, old_lr * self.params.lr_decay)
        if new_lr < old_lr:
            logger.info("Decreasing reverse direction learning rate: %.8f -> %.8f" % (old_lr, new_lr))
            self.map_optimizer(False).param_groups[0]['lr'] = new_lr

        if self.params.lr_shrink < 1 and to_log[metric] >= -1e7:
            if to_log[metric] < self.best_valid_metric:
                logger.info("Validation metric is smaller than the best: %.5f vs %.5f"
                            % (to_log[metric], self.best_valid_metric))
                # decrease the learning rate, only if this is the
                # second time the validation metric decreases
                if self.decrease_lr:
                    old_lr = self.map_optimizer(True).param_groups[0]['lr']
                    self.map_optimizer(True).param_groups[0]['lr'] *= self.params.lr_shrink
                    logger.info("Shrinking normal direction learning rate: %.5f -> %.5f"
                                % (old_lr, self.map_optimizer(True).param_groups[0]['lr']))


                    old_lr = self.map_optimizer(False).param_groups[0]['lr']
                    self.map_optimizer(False).param_groups[0]['lr'] *= self.params.lr_shrink
                    logger.info("Shrinking reverse direction learning rate: %.5f -> %.5f"
                                % (old_lr, self.map_optimizer(False).param_groups[0]['lr']))

                self.decrease_lr = True

    def save_best(self, to_log, metric):
        """
        Save the best model for the given validation metric.
        """
        # best mapping for the given validation criterion
        if to_log[metric] > self.best_valid_metric:
            # new best mapping
            self.best_valid_metric = to_log[metric]
            logger.info('* Best value for "%s": %.5f' % (metric, to_log[metric]))
     
            self.save_best_single(to_log, metric, True)
            self.save_best_single(to_log, metric, False)

    def save_best_single(self, to_log, metric, direction):
        # save the mapping
        W = self.mapping(direction).weight.data.cpu().numpy()
        path = os.path.join(self.params.exp_path, 'best_mapping_'+str(direction)+'.t7')
        logger.info('* Saving the mapping to %s ...' % path)
        torch.save(W, path)

    def reload_best(self):
        self.reload_best_single(True)
        self.reload_best_single(False)

    def reload_best_single(self, direction):
        """
        Reload the best mapping.
        """
        path = os.path.join(self.params.exp_path, 'best_mapping_'+str(direction)+'.t7')
        logger.info('* Reloading the best model from %s ...' % path)
        # reload the model
        assert os.path.isfile(path)
        to_reload = torch.from_numpy(torch.load(path))
        W = self.mapping(direction).weight.data
        assert to_reload.size() == W.size()
        W.copy_(to_reload.type_as(W))

    def export(self):
        """
        Export embeddings to a text file.
        """
        src_emb = self.mapping(True)(self.src_emb.weight).data
        tgt_emb = self.tgt_emb.weight.data
        src_emb = src_emb / src_emb.norm(2, 1, keepdim=True).expand_as(src_emb)
        tgt_emb = tgt_emb / tgt_emb.norm(2, 1, keepdim=True).expand_as(tgt_emb)
        export_embeddings(src_emb.cpu().numpy(), tgt_emb.cpu().numpy(), self.params)