# AUTOGENERATED! DO NOT EDIT! File to edit: 02_heusel2017gans.ipynb (unless otherwise specified).

__all__ = ['Inception', 'FIDMetric']

# Cell
from scipy import linalg
import torch
from torchvision.models.utils import load_state_dict_from_url
from fastprogress.fastprogress import master_bar, progress_bar
from fastai.data.external import untar_data
from fastai.data.transforms import get_image_files
from fastai.data import *
from fastai.basics import *
from fastai.vision.data import *
from fastai.vision.core import *
from fastcore.all import *
from fastai.vision.augment import *
from fastai.vision.gan import *
from .core import *
import torch.nn.functional as F

# Cell
class Inception(nn.Module):
    def __init__(self, weights='new', renormalize=False):
        super().__init__()
        #self.renormalize = renormalize
        self.renorm_func = Normalize.from_stats(*renorm_stats) if renormalize else noop
        if weights=='new':
            model = torch.hub.load('pytorch/vision:v0.6.0', 'inception_v3', pretrained=True)
        elif weights=='old':
            model = torch.hub.load('pytorch/vision:v0.6.0', 'inception_v3', pretrained=False, num_classes=1008)
            state_dict = load_state_dict_from_url(FID_WEIGHTS_URL, progress=True)
            model.load_state_dict(state_dict, strict=False)
        model.eval();
        model.fc = Identity()
        model.dropout = Identity()
        self.model = model
    def __call__(self, x):
        if min(x.shape[-2:])<299:
            x = F.interpolate(x, size=299)
        x = self.renorm_func(x)
        with torch.no_grad():
            return self.model(x)

# Cell
class FIDMetric(GenMetric):
    def __init__(self, model, dl, get_prediction=noop):
        self.get_prediction = get_prediction
        self.func = model
        if dl.device.type == 'cuda':
            self.func.cuda()
        total = []
        for b in progress_bar(dl):
            if isinstance(b, tuple):
                if len(b)==2:
                    b = b[1]
            b = b[-1] if is_listy(b) else b
            total.append(self.func(b))
        total = torch.cat(total).cpu()
        self.dist_norm = total.mean(axis=0).pow(2).sum().sqrt()
        self.dist_mean = total.mean(axis=0)
        self.dist_cov = (total-self.dist_mean).T@(total-self.dist_mean)/total.shape[0]
    def reset(self): self.total, self.count = [], 0
    def accumulate(self, learn):
        if learn.model.gen_mode:
            pred =  learn.pred[-1] if is_listy(learn.pred) else learn.pred
            self.total.append(learn.to_detach(self.func(pred)))
            self.count += 1

    @property
    def value(self):
        if self.count == 0: return None
        total = torch.cat(self.total).cpu()
        self.sample_mean = total.mean(axis=0).cpu()
        self.sample_cov = (total-self.sample_mean).T@(total-self.sample_mean)/total.shape[0]
        self.sample_cov = self.sample_cov.cpu()
        mean_loss = nn.MSELoss(reduction='sum')(self.sample_mean, self.dist_mean)
        cov_sqrt = linalg.sqrtm(self.sample_cov@self.dist_cov)
        if np.iscomplexobj(cov_sqrt):
            if not np.allclose(np.diagonal(cov_sqrt).imag, 0, atol=1e-3):
                m = np.max(np.abs(cov_sqrt.imag))
                raise ValueError("Imaginary component {}".format(m))
            cov_sqrt = cov_sqrt.real
        tcov1 = np.trace(self.sample_cov)
        tcov2 = np.trace(self.dist_cov)
        tcov_sqrt = np.trace(cov_sqrt)
        cov_loss = tcov1+tcov2-2*tcov_sqrt#np.trace(cov_sum - 2 * cov_sqrt)
        return mean_loss + cov_loss

    @property
    def name(self): return 'FID'