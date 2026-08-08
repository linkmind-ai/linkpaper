Alice Kim, Bob Lee

###### Abstract

We study section-aware chunking of research papers and show that it preserves
evidence boundaries better than fixed-window splitting.

1 Introduction
--------------

Recurrent models [[13](https://arxiv.org/html/2401.00001v1#bib.bib13)] have been
established as strong baselines for sequence modeling. We revisit this claim
with a controlled study.

![Image 1: Refer to caption](https://arxiv.org/html/2401.00001v1/figures/f1.png)

Figure 1: Overview of the proposed method.

2 Method
--------

Our method has two stages: section detection and size-bounded splitting.

### 2.1 Setup

We train on a corpus of 10k documents and evaluate retrieval quality.

### 2.2 Chunking

The splitter never crosses a section boundary.

```python
# 코드 블록 안의 밑줄은 제목이 아니다
value = "not a heading"
--------
```

3 Preference Learning
---------------------

We also compare against preference-based reranking. This heading contains the
word preference and must not be treated as a bibliography section.

References
----------

*   [1] Jimmy Lei Ba, Jamie Ryan Kiros, and Geoffrey E Hinton. Layer normalization. arXiv preprint arXiv:1607.06450, 2016.
*   [2] Dzmitry Bahdanau, Kyunghyun Cho, and Yoshua Bengio. Neural machine translation by jointly learning to align and translate. CoRR, abs/1409.0473, 2014.
*   [3] Denny Britz, Anna Goldie, Minh-Thang Luong, and Quoc V. Le. Massive exploration of neural machine translation architectures. arXiv:1703.03906, 2017.
*   [4] Jianpeng Cheng, Li Dong, and Mirella Lapata. Long short-term memory-networks for machine reading. arXiv preprint arXiv:1601.06733, 2016.
*   [5] Francois Chollet. Xception: Deep learning with depthwise separable convolutions. [https://arxiv.org/abs/1610.02357](https://arxiv.org/abs/1610.02357), 2016.
*   [6] Junyoung Chung and Caglar Gulcehre. Empirical evaluation of gated recurrent neural networks on sequence modeling. arXiv:1412.3555v2, 2014.
*   [7] Chris Dyer, Adhiguna Kuncoro, Miguel Ballesteros, and Noah A. Smith. Recurrent neural network grammars. In Proc. of NAACL, 2016.
*   [8] Jonas Gehring, Michael Auli, David Grangier, and Yann N. Dauphin. A convolutional encoder model for neural machine translation. arXiv:1611.02344, 2016.
*   [9] Alex Graves. Generating sequences with recurrent neural networks. arXiv preprint arXiv:1308.0850, 2013.
*   [10] Kaiming He, Xiangyu Zhang, Shaoqing Ren, and Jian Sun. Deep residual learning for image recognition. In CVPR, 2016.
*   [11] Sepp Hochreiter and Jurgen Schmidhuber. Long short-term memory. Neural Computation, 9(8):1735-1780, 1997.
*   [12] Rafal Jozefowicz, Oriol Vinyals, Mike Schuster, Noam Shazeer, and Yonghui Wu. Exploring the limits of language modeling. arXiv preprint arXiv:1602.02410, 2016.
*   [13] Nal Kalchbrenner, Lasse Espeholt, Karen Simonyan, and Aaron van den Oord. Neural machine translation in linear time. [arXiv:1610.10099](https://arxiv.org/abs/1610.10099), 2017.
*   [14] Yoon Kim, Carl Denton, Luong Hoang, and Alexander M. Rush. Structured attention networks. arXiv preprint arXiv:1702.00887, 2017.
*   [15] Diederik Kingma and Jimmy Ba. Adam: A method for stochastic optimization. In ICLR, 2015.
*   [16] Oleksii Kuchaiev and Boris Ginsburg. Factorization tricks for LSTM networks. arXiv preprint arXiv:1703.10722, 2017.
*   [17] Zhouhan Lin, Minwei Feng, Cicero Nogueira dos Santos, and Mo Yu. A structured self-attentive sentence embedding. arXiv preprint arXiv:1703.03130, 2017.
*   [18] Minh-Thang Luong, Hieu Pham, and Christopher D Manning. Effective approaches to attention-based neural machine translation. arXiv:1508.04025, 2015.
*   [19] Ankur Parikh, Oscar Tackstrom, Dipanjan Das, and Jakob Uszkoreit. A decomposable attention model. In EMNLP, 2016.
*   [20] Ofir Press and Lior Wolf. Using the output embedding to improve language models. arXiv preprint arXiv:1608.05859, 2016.
*   [21] Rico Sennrich, Barry Haddow, and Alexandra Birch. Neural machine translation of rare words with subword units. arXiv preprint arXiv:1508.07909, 2015.
*   [22] Noam Shazeer and Azalia Mirhoseini. Outrageously large neural networks. arXiv preprint arXiv:1701.06538, 2017.
*   [23] Nitish Srivastava, Geoffrey E Hinton, and Alex Krizhevsky. Dropout: a simple way to prevent neural networks from overfitting. JMLR, 15(1):1929-1958, 2014.
*   [24] Ilya Sutskever, Oriol Vinyals, and Quoc VV Le. Sequence to sequence learning with neural networks. In NIPS, 2014.
*   [25] Yonghui Wu and Mike Schuster. Google's neural machine translation system. arXiv preprint arXiv:1609.08144, 2016.
