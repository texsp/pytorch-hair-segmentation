import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import torch
import torch.nn as nn
import numpy as np

from external.MobileNetV2 import MobileNetV2
from torchvision import transforms

class Contractor(nn.Module):
    def __init__(self, pretrained=True):
        super(Contractor, self).__init__()
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        
        net = MobileNetV2()
        if pretrained:
            here = os.path.dirname(os.path.abspath(__file__))
            path = os.path.join(here, 'external/mobilenet_v2.pth.tar')
            net.load_state_dict(torch.load(path, map_location=self.device))
            
        # 0 ~ 7th layers    
        features = list(net.features.children())[:7]
        
        # 7 ~ 17th layers
        features_to_dilate = list(net.features.children())[7:18]
        dilated_features = self.dilate_last_features(features_to_dilate)
        
        # Main model
        self.contraction = nn.Sequential(*features, *dilated_features)
        
    def forward(self, x):
        x = self.contraction(x)
        return x
    
    @staticmethod
    def dilate_last_features(features):
        """
        This doesn't dilate the last kernels per se. It just
        sets the strides of all convolutional layers to (1,1)
        so that the output width and height are unaltered.
        """
        for inv_res in features:
            for layer in inv_res.conv:
                if isinstance(layer, nn.Conv2d) and layer.stride == (2, 2):
                    layer.stride = (1, 1)
        return features



class PointwiseConv(nn.Module):
    def __init__(self, cin, cout, bias=False):
        super(PointwiseConv, self).__init__()
        self.pw_conv = nn.Conv2d(cin, cout, 1, bias=bias)
        
    def forward(self, x):
        return self.pw_conv(x)

class DepthSepConv(nn.Module):  # 28, 64
    def __init__(self, cin, cout, kernel_size=3, stride=1, padding=1, bias=False):
        super(DepthSepConv, self).__init__()
        self.dw_conv = nn.Conv2d(cin, cin, kernel_size, stride, padding, bias=bias, groups=cin)
        self.batch_norm = nn.BatchNorm2d(cin)
        self.pw_conv = PointwiseConv(cin, cout, bias=bias)
        
    def forward(self, x):
        x = self.dw_conv(x)
        x = self.batch_norm(x)
        x = self.pw_conv(x)
        return x


class Inverter(nn.Module):
    def __init__(self, cin, cout, last=False, bias=False):
        super(Inverter, self).__init__()
        
        self.dw_sep_conv = DepthSepConv(cin, cout, bias=bias)
        self.batch_norm = nn.BatchNorm2d(cout)
        self.pw_conv = PointwiseConv(cout, cout, bias=bias)
        self.relu6 = nn.ReLU6() 
        
    def forward(self, x):
        x = nn.functional.interpolate(x, scale_factor=2)
        x = self.dw_sep_conv(x)
        x = self.batch_norm(x)
        x = self.pw_conv(x)
        x = self.relu6(x)
        return x
        

class Decoder(nn.Module):
    def __init__(self, cin, cout=1, cmid=64):
        super(Decoder, self).__init__()
        
        self.model = nn.Sequential(
            Inverter(cin, cmid),
            Inverter(cmid, cmid),
            Inverter(cmid, cmid),
            PointwiseConv(cmid, cout)
        )
        
    def forward(self, x):
        return self.model(x)



class FCN(nn.Module):
    def __init__(self):
        super(FCN, self).__init__()

        self.model = nn.Sequential(
            Contractor(False),
            Decoder(320, 1)
            )
        
    def forward(self, x):
        x = self.model(x)
        return x



if __name__ == '__main__':
    import time
    import torchsummary

    model = FCN()
    tensor = torch.randn((1,3,224,224))    
    print(tensor.shape)
    t0 = time.time()
    out = model(tensor)
    t1 = time.time()
    print(t1 - t0)
    print(out.shape)
    print(model)
    torchsummary.summary(model, (3,224,224))