import torch
import torch.nn as nn
from torch.autograd import Variable as V
import torch.nn.functional as F
import torchvision.datasets as datasets
import torchvision.transforms as transforms
import torch.optim as optim
import time
import matplotlib.pyplot as plt
import numpy as np

# New stuff.
from torch.distributions import Normal
from torch.distributions.kl import kl_divergence


# Functions to save/load models
def save_checkpoint(mod_enc, mod_dec, filename='checkpoint.pth.tar'):
    state_dict = {'model_encoder' : mod_enc.state_dict(),
                  'model_decoder' : mod_dec.state_dict()}
    torch.save(state_dict, filename)
def load_checkpoint(filename='checkpoint.pth.tar'):
    state_dict = torch.load(filename)
    return state_dict['model_encoder'], state_dict['model_decoder']
def set_parameters(model, sv_model, cuda=True):
    for i,p in enumerate(model.parameters()):
        p.data = sv_model[list(sv_model)[i]]
    if cuda:
        model.cuda()

class LatentModelUser(object):
    # Model order: [encoder, decoder, [VAE]], i.e. [disc, gen]
    # (since gen and decoder are very similar)
    def __init__(self, models, batch_sz=None, mode='vae', cuda=True):
        self.models = models
        self.cuda = cuda and torch.cuda.is_available()
        self.mode = mode
        self.bce_loss = nn.BCEWithLogitsLoss(size_average=False)        
        if self.cuda:
            print('Using CUDA...')
        else:
            print('CUDA is unavailable...')

        self.batch_sz = batch_sz
        # Set prior
        latent_dim = self.models[0].latent_dim
        self.prior = Normal(V(torch.zeros(self.batch_sz, latent_dim)), 
                            V(torch.ones(self.batch_sz, latent_dim)))

    def run_model_vae(self, batch, train=True, batch_avg=True):
        if train:
            for model in self.models:
                model.zero_grad()

        x = V(batch.type(torch.FloatTensor))
        out, q = self.models[2](x, enc_view_img=True, dec_view_img=False)

        # This is the NLL of the images according to the generative model out
        # x plays role of target
        x_view = x.view(-1, self.models[0].img_size)
        loss = self.bce_loss(out, x_view)
        if batch_avg:
            loss = loss / self.batch_sz
        # Important fact: kl divergence is additive for product
        # distributions, so we can do the KL divergence batch by batch
        # (and coordinate by coordinate within each data point)
        kl = kl_divergence(q, self.prior).sum()
        if batch_avg:
            kl = kl / self.batch_sz
        return loss, kl

    def run_disc_gan(self,  batch, train=True, batch_avg=True):
        if train:
            for opt in self.optimizers:
                opt.zero_grad()

        # Disc: -E[log(D(x))]
        x_real = V(batch.type(torch.FloatTensor))
        d_real = D(x_real)
        loss_d_real = 0.5 * -d_real.log.sum()

        # Disc: -E[log(1 - D(G(z)) )]
        seed = self.prior.sample()
        x_fake = G(seed)
        # Only backprop wrt disc parameters
        d_fake = D(x_fake.detach())        
        loss_d_fake = 0.5 * -(1 - d_fake + 1e-10).log().sum()

        if batch_avg:
            # TODO: confirm batch size is correct! (same in run_gen)
            loss_d_real = loss_d_real / self.batch_sz
            loss_d_fake = loss_d_fake / self.batch_sz
        return loss_d_real, loss_d_fake, x_fake

    def run_gen_gan(self, batch, x_fake=None, train=True, batch_avg=True)
        # Gen: E[log(1 - D(G(z)))]
        if train:
            # TODO: the sample code only zeros grad for disc (likely
            # b/c we only back-propagated wrt disc before)
            for opt in self.optimizers:
                opt.zero_grad()

        if x_fake is None:
            x_fake = G(self.prior.sample())
        # No detach here (we will not modify D parameters, but if we
        # do detach, we lose the gradients from the generator)
        d_fake = D(x_fake)
        loss_g = (1 - d_fake + 1e-10).log().sum()
        # loss_c = -(d + 1e-10).log().mean()
        if batch_avg:
            loss_g = loss_g / self.batch_sz
        return loss_g
    
class LatentModelEvaluator(LatentModelUser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def run_vae_generator(self, z_sample=None, fn=None, num_to_save=10):
        if z_sample is None:
            z_sample = V(self.prior.sample())
        out = F.sigmoid(self.models[1](z_sample, view_as_img=True))
        # Sample according to Bernoulli distribution for each pixel
        # TODO: sample for Bernoulli??
        x_gen = out.data # torch.bernoulli(out).data

        if not fn is None:
            self.plt_image(x_gen[:num_to_save].numpy(), base_fn=fn)
            
        return x_gen

    def interpolate_vae_generator(self, fn=None, num_to_save=10):
        # shape [batch_sz, latent_dim]
        z_sample_0 = V(self.prior.sample())
        z_sample_1 = V(self.prior.sample())
        x_gen_list = list()
        for alpha in np.arange(0, 1.2, 0.2):
            # Already called .data in run_vae_generator
            x_gen_list.append(self.run_vae_generator(
                alpha * z_sample_0 + (1 - alpha) * z_sample_1))

        if not fn is None:
            # Show images side by side
            x_gen_stack = np.concatenate(
                [x.numpy() for x in x_gen_list], axis=2)
            self.plt_image(x_gen_stack[:num_to_save], base_fn=fn)
        return x_gen_list

    def scatter_vae(self, test_loader, fn='vis/vae_scatter.png',
                    num_batch=None):
        assert self.models[0].latent_dim == 2
        latent_list = list()
        label_list = list()
        for i,batch in enumerate(test_loader):
            batch_img = V(batch[0])
            batch_lab = batch[1]
            # [batch_sz, 2]
            mu, _ = self.models[0](batch_img)
            latent_list += mu.data.numpy()
            label_list += batch_lab.data.numpy()
            if not num_batch is None and i >= num_batch:
                break
        latent_all = np.concatenate(latent_list, axis=0)
        label_all = np.concatenate(label_list, axis=0)
        plt.clf()
        plt.scatter(list(latent_all[:,0]), list(latent_all[:,1]),
                    c=list(label_all))
        plg.legend()
        plt.savefig(fn)

    def plt_image(self, x, base_fn='vis/', grid=False):
        if grid:
            # x is [K, K, ht, width]
            big_x = np.zeros(x.shape[0] * x.shape[2],
                             x.shape[1] * x.shape[3])
            K = x.shape[0]
            for ix in range(K):
                for iy in range(K):
                    big_x[ix * K:(ix+1) * K,iy * K:(iy+1) * K] = \
                            x[ix, iy, :, :]
            plt.clf()
            plt.imshow(1 - big_x, cmap='gray')
            plt.axis('off')
            if base_fn == 'vis/':
                base_fn += 'big_img.png'
            plt.savefig(base_fn)
        else:
            for i in range(x.shape[0]):
               plt.clf()
               plt.imshow(1 - x[i,:,:], cmap='gray')
               plt.axis('off')
               plt.savefig(base_fn + '%d.png' % i)

    def grid_vae(self, fn='vis/vae_grid.png'):
        assert self.models[0].latent_dim == 2
        latent_disc = 10
        z1, z2 = np.meshgrid(np.linspace(-2, 2, latent_disc),
                             np.linspace(-2, 2, latent_disc))
        z1 = z1.reshape(-1)
        z2 = z2.reshape(-2)
        z = V(torch.FloatTensor(np.stack((z1, z2), axis=1)))
        # Has incorrect batch size, but that should be ok
        # shape [batch_sz, img_height, img_width]
        x_img = self.run_vae_generator(z).numpy()
        x_img = x_img.reshape((latent_disc, latent_disc,
                               x_img.shape[1], x_img.shape[2]))
        self.plt_image(x_img, base_fn=fn, grid=True)

    def make_vae_plots(self, test_loader, num_batch=None):
        for model in self.models:
            model.eval()

        self.run_vae_generator(fn='vis/vae_generator', num_to_save=3)
        self.interpolate_vae_generator(fn='vis/vae_interpolation', num_to_save=3)
        if self.models[0].latent_dim == 2:
            self.scatter_vae(test_loader, fn='vis/vae_scatter.png', num_batch=num_batch)
            self.grid_vae(fn='vis/vae_grid.png')
        

    def evaluate(self, val_loader, num_iter=None):
        start_time = time.time()
        for model in self.models:
            model.eval()

        loss_0_sum = 0
        loss_1_sum = 0
        data_cnt = 0

        # Since this is a conditionally conjugate model with no global
        # latent variables (i.e. only latent variables) and the KL
        # divergences are between product distributions (for both
        # prior and conditional; i.e. it is a random field), we can
        # compute KL divergence and NLL in batches
        for i,batch in enumerate(val_loader):
            batch = batch[0] # Ignore label
            if self.mode == 'vae':
                loss, kl = self.run_model_vae(batch, train=False, batch_avg=False)
                loss_0_sum += loss.data.item()
                loss_1_sum += kl.data.item()
            elif self.mode == 'gan':
                loss_d_real, loss_d_fake, x_fake = \
                    self.run_disc_gan(batch, train=False, batch_avg=False)
                loss_g = self.run_gen_gan(batch, x_fake, train=False,
                                          batch_avg=False)
                loss_0_sum += loss_d_real.data.item() + loss_d_fake.data.item()
                loss_1_sum += loss_g.data.item()
            else:
               raise ValueError('Invalid mode %s' % self.mode)
           
           data_cnt += batch.size(0)

           if not num_iter is None and i >= num_iter:
               break

        loss_0_avg = loss_0_sum / data_cnt
        loss_1_avg = loss_1_sum / data_cnt

        return loss_0_avg, loss_1_avg
        
            

class LatentModelTrainer(LatentModelUser):
    def __init__(self, *args, lrn_rate=0.05, optimizer=optim.SGD, **kwargs):
        super().__init__(*args, **kwargs)
        self.base_lrn_rate = lrn_rate
        self.optimizer_type = optimizer
        self.init_optimizers()
        if self.cuda:
            for model in self.models:
                model.cuda()
        
    def init_parameters(self):
        for model in self.models:
            for p in model.parameters():
                p.data.uniform_(-0.05, 0.05)

    def train_save_model(self, save_model_fn, epoch):
        pathname = 'saved_models/' + save_model_fn + \
                   '.epoch_%d.ckpt.tar' % epoch
        print('Saving model to %s' % pathname)
        save_checkpoint(self.models[0], self.models[1],
                   pathname)

class GANLatentModelTrainer(LatentModelTrainer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def init_optimizers(self):
        self.optimizers = [self.optimizer_type(filter(lambda p : p.requires_grad,
                                                      model.parameters()),
                                               lr = self.base_lrn_rate) for \
                           model in self.models]

    def init_lists(self):
        self.training_disc_losses = list()
        self.training_gen_losses = list()
        self.val_disc_losses = list()
        self.val_gen_losses = list()

    # Training is different enough for GANs that we use a separate
    # train function
    def train(self, train_loader, save_model_fn=None, le=None,
              val_loader=None, init_parameters=True, num_epochs=100,
              skip_epochs=1, gan_k=1, **kwargs):
        start_time = time.time()
        self.init_lists()
        if init_parameters:
            self.init_parameters()

        for epoch in range(num_epochs):
            for model in self.model:
                model.train()

            self.training_disc_losses.append(0)
            self.training_gen_losses.append(0)
            for i,batch in enumerate(train_loader):
                batch = batch[0] # Ignore labels

                for k in range(gan_k):
                    loss_d_real, loss_d_fake, x_fake = \
                        self.run_disc_gan(batch, train=True, batch_avg=True)
                    loss_d_real.backward()
                    loss_d_fake.backward()
                    self.optimizers[0].step()
                    self.training_disc_losses[-1] += loss_d_real.data.item() + loss_d_fake.data.item()

                loss_g = self.run_gen_gan(batch, x_fake, train=True,
                                          batch_avg=True)
                loss_g.backward()
                self.optimizers[1].step()
                self.training_gen_losses[-1] += loss_g.data.item()
            self.training_disc_losses[-1] /= len(train_loader)
            self.training_gen_losses[-1] /= len(train_loader)

            print('Epoch %d, disc loss: %f, gen_loss: %f, lrn_rate: %f, elapsed: %f' \
                  % (epoch, self.training_disc_losses[-1],
                     self.training_gen_losses[-1],
                     self.base_lrn_rate, time.time() - start_time))

            if (not le is None) and (not val_loader is None):
                loss_d_val, loss_g_val = le.evaluate(val_loader)
                self.val_disc_losses.append(loss_d_val)
                self.val_gen_losses.append(loss_g_val)

                print('Validation set: disc loss: %f, gen loss: %f' \
                      % (loss_d_val, loss_g_val))


            if (epoch % skip_epochs == 0) and (not save_model_fn is None):
                self.train_save_model(save_model_fn, epoch)

class VAELatentModelTrainer(LatentModelTrainer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
    def init_optimizers(self):
        self.optimizer = self.optimizer_type(filter(lambda p : p.requires_grad,
                                                    self.models[2].parameters()),
                                             lr = self.base_lrn_rate)

        
    def init_lists(self):
        self.training_losses = list()
        self.training_kls = list()
        self.val_losses = list()
        self.val_kls = list()


    def train(self, train_loader, save_model_fn=None, le=None, val_loader=None,
              init_parameters=True, num_epochs=100, skip_epochs=1, **kwargs):
        start_time = time.time()
        self.init_lists()
        if init_parameters:
            self.init_parameters()

        for epoch in range(num_epochs):
            for model in self.models:
                model.train()

            self.training_losses.append(0)
            self.training_kls.append(0)
            for i, batch in enumerate(train_loader):
                batch = batch[0] # Ignore labels
                loss, kl = self.run_model_vae(batch, **kwargs)
                loss_comb = loss + kl
                loss_comb.backward()
                self.optimizer.step()

                # print('loss', loss, loss.data)
                # print('kl', kl, kl.data)
                self.training_losses[-1] += loss.data.item()
                self.training_kls[-1] += kl.data.item()
            self.training_losses[-1] /= len(train_loader)
            self.training_kls[-1] /= len(train_loader)

            print('Epoch %d, loss: %f, KL: %f, lrn_rate: %f, elapsed: %f' \
                  % (epoch, self.training_losses[-1], self.training_kls[-1],
                     self.base_lrn_rate, time.time() - start_time))

            if (not le is None) and (not val_loader is None):
                val_loss, val_kl = le.evaluate(val_loader)
                self.val_losses.append(val_loss)
                self.val_kls.append(val_kl)

                print('Validation set: loss: %f, KL: %f' \
                      % (val_loss, val_kl))


            if (epoch % skip_epochs == 0) and (not save_model_fn is None):
                self.train_save_model(save_model_fn, epoch)

