import torch.nn as nn
import torch.nn.functional as F
from utils.utils import *
import torch

# this function works for building the groud truth
def build_targets(pred_boxes, target, anchors, num_anchors, num_classes, nH, nW, noobject_scale, object_scale, sil_thresh, seen):
    # nH, nW here are number of grids in y and x directions (7, 7 here)
    nB = target.size(0) # batch size
    nA = num_anchors    # 5 for our case
    nC = num_classes
    anchor_step = len(anchors)//num_anchors
    conf_mask  = torch.ones(nB, nA, nH, nW) * noobject_scale
    coord_mask = torch.zeros(nB, nA, nH, nW)
    cls_mask   = torch.zeros(nB, nA, nH, nW)
    tx         = torch.zeros(nB, nA, nH, nW)
    ty         = torch.zeros(nB, nA, nH, nW)
    tw         = torch.zeros(nB, nA, nH, nW)
    th         = torch.zeros(nB, nA, nH, nW)
    tconf      = torch.zeros(nB, nA, nH, nW)
    tcls       = torch.zeros(nB, nA, nH, nW)

    # for each grid there are nA anchors
    # nAnchors is the number of anchor for one image
    nAnchors = nA*nH*nW
    nPixels  = nH*nW
    # for each image
    for b in range(nB):
        # get all anchor boxes in one image
        # (4 * nAnchors)
        cur_pred_boxes = pred_boxes[b*nAnchors:(b+1)*nAnchors].t()
        # initialize iou score for each anchor
        cur_ious = torch.zeros(nAnchors)
        for t in range(50):
            # for each anchor 4 coordinate parameters, already in the coordinate system for the whole image
            # this loop is for anchors in each image
            # for each anchor 5 parameters are available (class, x, y, w, h)
            if target[b][t*5+1] == 0:
                break
            gx = target[b][t*5+1]*nW/608
            gy = target[b][t*5+2]*nH/608
            gw = target[b][t*5+3]*nW/608
            gh = target[b][t*5+4]*nH/608
            # groud truth boxes
            cur_gt_boxes = torch.FloatTensor([gx,gy,gw,gh]).repeat(nAnchors,1).t()
            # bbox_ious is the iou value between orediction and groud truth
            cur_ious = torch.max(cur_ious, bbox_ious(cur_pred_boxes, cur_gt_boxes, x1y1x2y2=False))
        # if iou > a given threshold, it is seen as it includes an object
        # conf_mask[b][cur_ious>sil_thresh] = 0
        conf_mask_t = conf_mask.view(nB, -1)
        conf_mask_t[b][cur_ious>sil_thresh] = 0
        conf_mask_tt = conf_mask_t[b].view(nA, nH, nW)
        conf_mask[b] = conf_mask_tt

    if seen < 12800:
       if anchor_step == 4:
           tx = torch.FloatTensor(anchors).view(nA, anchor_step).index_select(1, torch.LongTensor([2])).view(1,nA,1,1).repeat(nB,1,nH,nW)
           ty = torch.FloatTensor(anchors).view(num_anchors, anchor_step).index_select(1, torch.LongTensor([2])).view(1,nA,1,1).repeat(nB,1,nH,nW)
       else:
           tx.fill_(0.5)
           ty.fill_(0.5)
       tw.zero_()
       th.zero_()
       coord_mask.fill_(1)



    # number of ground truth
    nGT = 0
    nCorrect = 0
    for b in range(nB):
        # anchors for one batch (at least batch size, and for some specific classes, there might exist more than one anchor)
        for t in range(50):
            if target[b][t*5+1] == 0:
                break
            nGT = nGT + 1
            best_iou = 0.0
            best_n = -1
            min_dist = 10000
            # the values saved in target is ratios
            # times by the width and height of the output feature maps nW and nH
            gx = target[b][t*5+1] * nW/608
            gy = target[b][t*5+2] * nH/608
            gi = int(gx)
            gj = int(gy)
            gw = target[b][t*5+3] * nW/608
            gh = target[b][t*5+4] * nH/608
            gt_box = [0, 0, gw, gh]
            for n in range(nA):
                # get anchor parameters (2 values)
                aw = anchors[anchor_step*n]
                ah = anchors[anchor_step*n+1]
                anchor_box = [0, 0, aw, ah]
                # only consider the size (width and height) of the anchor box
                iou  = bbox_iou(anchor_box, gt_box, x1y1x2y2=False)
                if anchor_step == 4:
                    ax = anchors[anchor_step*n+2]
                    ay = anchors[anchor_step*n+3]
                    dist = pow(((gi+ax) - gx), 2) + pow(((gj+ay) - gy), 2)
                # get the best anchor form with the highest iou
                if iou > best_iou:
                    best_iou = iou
                    best_n = n
                elif anchor_step==4 and iou == best_iou and dist < min_dist:
                    best_iou = iou
                    best_n = n
                    min_dist = dist

            # then we determine the parameters for an anchor (4 values together)
            gt_box = [gx, gy, gw, gh]
            # find corresponding prediction box
            pred_box = pred_boxes[b*nAnchors+best_n*nPixels+gj*nW+gi]
            # print(anchors[anchor_step*best_n])
            # only consider the best anchor box, for each image
            coord_mask[b][best_n][gj][gi] = 1
            cls_mask[b][best_n][gj][gi] = 1
            # in this cell of the output feature map, there exists an object
            conf_mask[b][best_n][gj][gi] = object_scale
            tx[b][best_n][gj][gi] = target[b][t*5+1] * nW/608 - gi
            ty[b][best_n][gj][gi] = target[b][t*5+2] * nH/608 - gj
            tw[b][best_n][gj][gi] = math.log(gw/anchors[anchor_step*best_n])
            th[b][best_n][gj][gi] = math.log(gh/anchors[anchor_step*best_n+1])
            iou = bbox_iou(gt_box, pred_box, x1y1x2y2=False) # best_iou
            # confidence equals to iou of the corresponding anchor
            tconf[b][best_n][gj][gi] = iou
            tcls[b][best_n][gj][gi] = target[b][t*5]
            # if ious larger than 0.5, we justify it as a correct prediction
            if iou > 0.5:
                nCorrect = nCorrect + 1

    # true values are returned
    return nGT, nCorrect, coord_mask, conf_mask, cls_mask, tx, ty, tw, th, tconf, tcls


class YoloLayer(nn.Module):
    def __init__(self, anchor_mask=[], num_classes=0, anchors=[], num_anchors=1,stride=32):
        super(YoloLayer, self).__init__()
        self.boxes = []
        self.anchor_mask = anchor_mask
        self.num_classes = num_classes
        self.anchors = anchors
        self.num_anchors = num_anchors
        self.anchor_step = len(anchors) // num_anchors
        self.coord_scale = 1
        self.noobject_scale = 1
        self.object_scale = 5
        self.class_scale = 1
        self.thresh = 0.6
        self.stride = stride
        self.seen = 0

    def forward(self, output, target=None):
        masked_anchors = []
        for m in self.anchor_mask:
            masked_anchors += self.anchors[m * self.anchor_step:(m + 1) * self.anchor_step]
        masked_anchors = [anchor / self.stride for anchor in masked_anchors]

        if target is not None:
            # masked_anchors = []
            # for m in self.anchor_mask:
            #     masked_anchors += self.anchors[m * self.anchor_step:(m + 1) * self.anchor_step]
            # masked_anchors = [anchor / self.stride for anchor in masked_anchors]
            # output : B*A*(4+1+num_classes)*H*W
            # B: number of batches
            # A: number of anchors
            # 4: 4 parameters for each bounding box
            # 1: confidence score
            # num_classes
            # H: height of the image (in grids)
            # W: width of the image (in grids)
            # for each grid cell, there are A*(4+1+num_classes) parameters
            nB = output.data.size(0)
            nA = len(self.anchor_mask)
            nC = self.num_classes
            nH = output.data.size(2)
            nW = output.data.size(3)
            t0 = time.time()
            # resize the output (all parameters for each anchor can be reached)
            output = output.view(nB, nA, (5 + nC), nH, nW)
            # anchor's parameter tx
            x = torch.sigmoid(output.index_select(2, Variable(torch.cuda.LongTensor([0]))).view(nB, nA, nH, nW))
            # anchor's parameter ty
            y = torch.sigmoid(output.index_select(2, Variable(torch.cuda.LongTensor([1]))).view(nB, nA, nH, nW))
            # anchor's parameter tw
            w = output.index_select(2, Variable(torch.cuda.LongTensor([2]))).view(nB, nA, nH, nW)
            # anchor's parameter th
            h = output.index_select(2, Variable(torch.cuda.LongTensor([3]))).view(nB, nA, nH, nW)
            # confidence score for each anchor
            conf = torch.sigmoid(output.index_select(2, Variable(torch.cuda.LongTensor([4]))).view(nB, nA, nH, nW))
            # anchor's parameter class label
            cls = output.index_select(2, Variable(torch.linspace(5, 5 + nC - 1, nC).long().cuda()))
            # resize the data structure so that for every anchor there is a class label in the last dimension
            cls = cls.view(nB * nA, nC, nH * nW).transpose(1, 2).contiguous().view(nB * nA * nH * nW, nC)
            t1 = time.time()

            # for the prediction of localization of each bounding box, there exist 4 parameters (tx, ty, tw, th)
            pred_boxes = torch.cuda.FloatTensor(4, nB * nA * nH * nW)
            # tx and ty
            grid_x = torch.linspace(0, nW - 1, nW).repeat(nH, 1).repeat(nB * nA, 1, 1).view(
                nB * nA * nH * nW).cuda()
            grid_y = torch.linspace(0, nH - 1, nH).repeat(nW, 1).t().repeat(nB * nA, 1, 1).view(
                nB * nA * nH * nW).cuda()
            # for each anchor there are anchor_step variables (with the structure num_anchor*anchor_step)
            # for each row(anchor), the first variable is anchor's width, second is anchor's height
            # pw and ph
            anchor_w = torch.Tensor(masked_anchors).view(nA, self.anchor_step).index_select(1,
                                                                                            torch.LongTensor(
                                                                                                [0])).cuda()
            anchor_h = torch.Tensor(masked_anchors).view(nA, self.anchor_step).index_select(1,
                                                                                            torch.LongTensor(
                                                                                                [1])).cuda()
            # for each pixel (grid) repeat the above process (obtain width and height of each grid)
            anchor_w = anchor_w.repeat(nB, 1).repeat(1, 1, nH * nW).view(nB * nA * nH * nW)
            anchor_h = anchor_h.repeat(nB, 1).repeat(1, 1, nH * nW).view(nB * nA * nH * nW)
            # prediction of bounding box localization
            # x.data and y.data: top left corner of the anchor
            # grid_x, grid_y: tx and ty predictions made by yowo

            x_data = x.data.view(-1)
            y_data = y.data.view(-1)
            w_data = w.data.view(-1)
            h_data = h.data.view(-1)

            pred_boxes[0] = x_data + grid_x  # bx
            pred_boxes[1] = y_data + grid_y  # by
            pred_boxes[2] = torch.exp(w_data) * anchor_w  # bw
            pred_boxes[3] = torch.exp(h_data) * anchor_h  # bh
            # the size -1 is inferred from other dimensions
            # pred_boxes (nB*nA*nH*nW, 4)
            pred_boxes = convert2cpu(pred_boxes.transpose(0, 1).contiguous().view(-1, 4))
            t2 = time.time()

            nGT, nCorrect, coord_mask, conf_mask, cls_mask, tx, ty, tw, th, tconf, tcls = build_targets(pred_boxes,
                                                                                                        target.data,
                                                                                                        masked_anchors,
                                                                                                        nA, nC, \
                                                                                                        nH, nW,
                                                                                                        self.noobject_scale,
                                                                                                        self.object_scale,
                                                                                                        self.thresh,
                                                                                                        self.seen)
            cls_mask = (cls_mask == 1)
            #  keep those with high box confidence scores (greater than 0.25) as our final predictions
            nProposals = int((conf > 0.25).sum().data.item())

            tx = Variable(tx.cuda())
            ty = Variable(ty.cuda())
            tw = Variable(tw.cuda())
            th = Variable(th.cuda())
            tconf = Variable(tconf.cuda())
            tcls = Variable(tcls.view(-1)[cls_mask.view(-1)].long().cuda())
            A = w[w < -0.14]
            coord_mask = Variable(coord_mask.cuda())
            conf_mask = Variable(conf_mask.cuda().sqrt())
            cls_mask = Variable(cls_mask.view(-1, 1).repeat(1, nC).cuda())
            cls = cls[cls_mask].view(-1, nC)

            # mask = torch.gt(conf,0.8)

            # print(torch.argmax(cls,dim=1))
            t3 = time.time()

            loss_x = self.coord_scale * nn.MSELoss(size_average=False)(x * coord_mask, tx * coord_mask) / 2.0
            loss_y = self.coord_scale * nn.MSELoss(size_average=False)(y * coord_mask, ty * coord_mask) / 2.0
            loss_w = self.coord_scale * nn.MSELoss(size_average=False)(w * coord_mask, tw * coord_mask) / 2.0
            loss_h = self.coord_scale * nn.MSELoss(size_average=False)(h * coord_mask, th * coord_mask) / 2.0
            loss_conf = nn.MSELoss(size_average=False)(conf * conf_mask, tconf * conf_mask) / 2.0
            loss_cls = self.class_scale * nn.CrossEntropyLoss(size_average=False)(cls, tcls)

            loss = loss_x + loss_y + loss_w + loss_h + loss_conf + loss_cls
            t4 = time.time()
            if False:
                print('-----------------------------------')
                print('        activation : %f' % (t1 - t0))
                print(' create pred_boxes : %f' % (t2 - t1))
                print('     build targets : %f' % (t3 - t2))
                print('       create loss : %f' % (t4 - t3))
                print('             total : %f' % (t4 - t0))
            # # print('%d: nGT %d, recall %d, proposals %d, loss: x %f, y %f, w %f, h %f, conf %f, cls %f, total %f' % (
            # # self.seen, nGT, nCorrect, nProposals, loss_x.data[0], loss_y.data[0], loss_w.data[0], loss_h.data[0],
            # # loss_conf.data[0], loss_cls.data[0], loss.data[0]))
            return loss

        else:
            nB = output.data.size(0)
            nA = len(self.anchor_mask)
            nC = self.num_classes
            nH = output.data.size(2)
            nW = output.data.size(3)

            output = output.permute(0, 2, 3, 1)
            output = output.reshape(output.size(0), output.size(1), output.size(2), 3, -1)
            mask = torch.sigmoid(output[..., 4]) > 0.98

            idxs = torch.nonzero(mask)
            vecs = output[mask]
            if vecs.shape[0] != 0:
                a = idxs[:, 3]

                masked_anchors = torch.tensor(masked_anchors).cuda()
                pre_x = (idxs[:, 2].float() + torch.sigmoid(vecs[:, 0])) * 608 / nW
                pre_y = (idxs[:, 1].float() + torch.sigmoid(vecs[:, 1])) * 608 / nH
                pre_w = masked_anchors[a * 2] * torch.exp(vecs[:, 2]) * 608 / nW
                pre_h = masked_anchors[a * 2 + 1] * torch.exp(vecs[:, 3]) * 608 / nH

                pre_x1 = pre_x - 0.5 * pre_w
                pre_y1 = pre_y - 0.5 * pre_h
                pre_x2 = pre_x + 0.5 * pre_w
                pre_y2 = pre_y + 0.5 * pre_h
                iou = torch.sigmoid(vecs[:, 4])
                kind = torch.argmax(vecs[:, 5:85], dim=1).float()
                box = torch.stack([iou, pre_x1, pre_y1, pre_x2, pre_y2, kind], dim=1)
                box = np.array(box.data.cpu())

                return box
