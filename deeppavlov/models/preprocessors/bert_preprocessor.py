# Copyright 2017 Neural Networks and Deep Learning lab, MIPT
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import random
import re
from logging import getLogger
from typing import Tuple, List, Optional, Union

import numpy as np
from bert_dp.preprocessing import convert_examples_to_features, InputExample, InputFeatures
from bert_dp.tokenization import FullTokenizer

from deeppavlov.core.commands.utils import expand_path
from deeppavlov.core.common.registry import register
from deeppavlov.core.data.utils import zero_pad
from deeppavlov.core.models.component import Component

log = getLogger(__name__)


@register('bert_preprocessor')
class BertPreprocessor(Component):
    """Tokenize text on subtokens, encode subtokens with their indices, create tokens and segment masks.

    Check details in convert_examples_to_features function.

    Args:
        vocab_file: path to vocabulary
        do_lower_case: set True if lowercasing is needed
        max_seq_length: max sequence length in subtokens, including [SEP] and [CLS] tokens

    Attributes:
        max_seq_length: max sequence length in subtokens, including [SEP] and [CLS] tokens
        tokenizer: instance of Bert FullTokenizer
    """

    def __init__(self,
                 vocab_file: str,
                 do_lower_case: bool = True,
                 max_seq_length: int = 512,
                 **kwargs) -> None:
        self.max_seq_length = max_seq_length
        vocab_file = str(expand_path(vocab_file))
        self.tokenizer = FullTokenizer(vocab_file=vocab_file,
                                       do_lower_case=do_lower_case)

    def __call__(self, texts_a: List[str], texts_b: Optional[List[str]] = None) -> List[InputFeatures]:
        """Call Bert convert_examples_to_features function to tokenize and create masks.

        texts_a and texts_b are separated by [SEP] token

        Args:
            texts_a: list of texts,
            texts_b: list of texts, it could be None, e.g. single sentence classification task

        Returns:
            batch of InputFeatures with subtokens, subtoken ids, subtoken mask, segment mask.

        """

        if texts_b is None:
            texts_b = [None] * len(texts_a)
        # unique_id is not used
        examples = [InputExample(unique_id=0, text_a=text_a, text_b=text_b)
                    for text_a, text_b in zip(texts_a, texts_b)]
        return convert_examples_to_features(examples, self.max_seq_length, self.tokenizer)


@register('bert_ner_preprocessor')
class BertNerPreprocessor(Component):
    """Takes tokens and splits them into bert subtokens, encode subtokens with their indices.
    Creates mask of subtokens (one for first subtoken, zero for later subtokens).

    If tags are provided, calculate tags for subtokens.

    Args:
        vocab_file: path to vocabulary
        do_lower_case: set True if lowercasing is needed
        max_seq_length: max sequence length in subtokens, including [SEP] and [CLS] tokens
        max_subword_length: replace token to <unk> if it's length is larger than this
            (defaults to None, which is equal to +infinity)
        token_mask_prob: probability of masking token while training
        provide_subword_tags: output tags for subwords or for words

    Attributes:
        max_seq_length: max sequence length in subtokens, including [SEP] and [CLS] tokens
        max_subword_length: rmax lenght of a bert subtoken
        tokenizer: instance of Bert FullTokenizer
    """

    def __init__(self,
                 vocab_file: str,
                 do_lower_case: bool = False,
                 max_seq_length: int = 512,
                 max_subword_length: int = None,
                 token_maksing_prob: float = 0.0,
                 provide_subword_tags: bool = False,
                 **kwargs):
        self._re_tokenizer = re.compile(r"[\w']+|[^\w ]")
        self.provide_subword_tags = provide_subword_tags
        self.mode = kwargs.get('mode')
        self.max_seq_length = max_seq_length
        self.max_subword_length = max_subword_length
        vocab_file = str(expand_path(vocab_file))
        self.tokenizer = FullTokenizer(vocab_file=vocab_file,
                                       do_lower_case=do_lower_case)
        self.token_maksing_prob = token_maksing_prob

    def __call__(self,
                 tokens: Union[List[List[str]], List[str]],
                 tags: List[List[str]] = None,
                 **kwargs):
        if isinstance(tokens[0], str):
            tokens = [re.findall(self._re_tokenizer, s) for s in tokens]
        subword_tokens, subword_tok_ids, subword_masks, subword_tags = [], [], [], []
        for i in range(len(tokens)):
            toks = tokens[i]
            ys = ['O'] * len(toks) if tags is None else tags[i]
            mask = [int(y != 'X') for y in ys]
            assert len(toks) == len(ys) == len(mask), \
                f"toks({len(toks)}) should have the same length as " \
                f" ys({len(ys)}) and mask({len(mask)}), tokens = {toks}."
            sw_toks, sw_mask, sw_ys = self._ner_bert_tokenize(toks,
                                                              mask,
                                                              ys,
                                                              self.tokenizer,
                                                              self.max_subword_length,
                                                              mode=self.mode,
                                                              token_maksing_prob=self.token_maksing_prob)
            if self.max_seq_length is not None:
                if len(sw_toks) > self.max_seq_length:
                    sw_toks = sw_toks[:self.max_seq_length]
                    sw_mask = sw_mask[:self.max_seq_length]
                    sw_ys = sw_ys[:self.max_seq_length]
            subword_tokens.append(sw_toks)
            subword_tok_ids.append(self.tokenizer.convert_tokens_to_ids(sw_toks))
            subword_masks.append(sw_mask)
            subword_tags.append(sw_ys)
            assert len(sw_mask) == len(sw_toks) == len(subword_tok_ids[-1]) == len(sw_ys), \
                f"length of mask({len(sw_mask)}), tokens({len(sw_toks)})," \
                f" token ids({len(subword_tok_ids[-1])}) and ys({len(ys)})" \
                f" for tokens = `{toks}` should match"
        subword_tok_ids = zero_pad(subword_tok_ids, dtype=int, padding=0)
        subword_masks = zero_pad(subword_masks, dtype=int, padding=0)
        if tags is not None:
            if self.provide_subword_tags:
                return tokens, subword_tokens, subword_tok_ids, subword_masks, subword_tags
            else:
                nonmasked_tags = [[t for t in ts if t != 'X'] for ts in tags]
                for swts, swids, swms, ts in zip(subword_tokens,
                                                 subword_tok_ids,
                                                 subword_masks,
                                                 nonmasked_tags):
                    if (len(swids) != len(swms)) or (len(ts) != sum(swms)):
                        log.warning('Not matching lengths of the tokenization!')
                        log.warning(f'Tokens len: {len(swts)}\n Tokens: {swts}')
                        log.warning(f'Masks len: {len(swms)}, sum: {sum(swms)}')
                        log.warning(f'Masks: {swms}')
                        log.warning(f'Tags len: {len(ts)}\n Tags: {ts}')
                return tokens, subword_tokens, subword_tok_ids, subword_masks, nonmasked_tags
        return tokens, subword_tokens, subword_tok_ids, subword_masks

    @staticmethod
    def _ner_bert_tokenize(tokens: List[str],
                           mask: List[int],
                           tags: List[str],
                           tokenizer: FullTokenizer,
                           max_subword_len: int = None,
                           mode: str = None,
                           token_maksing_prob: float = 0.0) -> Tuple[List[str], List[int], List[str]]:
        tokens_subword = ['[CLS]']
        mask_subword = [0]
        tags_subword = ['X']
        for token, flag, tag in zip(tokens, mask, tags):
            subwords = tokenizer.tokenize(token)
            if not subwords or \
                    ((max_subword_len is not None) and (len(subwords) > max_subword_len)):
                tokens_subword.append('[UNK]')
                mask_subword.append(flag)
                tags_subword.append(tag)
            else:
                if mode == 'train' and token_maksing_prob > 0.0 and np.random.rand() < token_maksing_prob:
                    tokens_subword.extend(['[MASK]'] * len(subwords))
                else:
                    tokens_subword.extend(subwords)
                mask_subword.extend([flag] + [0] * (len(subwords) - 1))
                tags_subword.extend([tag] + ['X'] * (len(subwords) - 1))

        tokens_subword.append('[SEP]')
        mask_subword.append(0)
        tags_subword.append('X')
        return tokens_subword, mask_subword, tags_subword


@register('bert_ranker_preprocessor')
class BertRankerPreprocessor(BertPreprocessor):
    """Tokenize text to sub-tokens, encode sub-tokens with their indices, create tokens and segment masks for ranking.

    Builds features for a pair of context with each of the response candidates.
    """

    def __call__(self, batch: List[List[str]]) -> List[List[InputFeatures]]:
        """Call BERT convert_examples_to_features function to tokenize and create masks.

        Args:
            batch: list of elemenents where the first element represents the batch with contexts
                and the rest of elements represent response candidates batches

        Returns:
            list of feature batches with subtokens, subtoken ids, subtoken mask, segment mask.
        """

        if isinstance(batch[0], str):
            batch = [batch]

        cont_resp_pairs = []
        if len(batch[0]) == 1:
            contexts = batch[0]
            responses_empt = [None] * len(batch)
            cont_resp_pairs.append(zip(contexts, responses_empt))
        else:
            contexts = [el[0] for el in batch]
            for i in range(1, len(batch[0])):
                responses = []
                for el in batch:
                    responses.append(el[i])
                cont_resp_pairs.append(zip(contexts, responses))
        examples = []
        for s in cont_resp_pairs:
            ex = [InputExample(unique_id=0, text_a=context, text_b=response) for context, response in s]
            examples.append(ex)
        features = [convert_examples_to_features(el, self.max_seq_length, self.tokenizer) for el in examples]

        return features


@register('bert_sep_ranker_preprocessor')
class BertSepRankerPreprocessor(BertPreprocessor):
    """Tokenize text to sub-tokens, encode sub-tokens with their indices, create tokens and segment masks for ranking.

    Builds features for a context and for each of the response candidates separately.
    """

    def __call__(self, batch: List[List[str]]) -> List[List[InputFeatures]]:
        """Call BERT convert_examples_to_features function to tokenize and create masks.

        Args:
            batch: list of elemenents where the first element represents the batch with contexts
                and the rest of elements represent response candidates batches

        Returns:
            list of feature batches with subtokens, subtoken ids, subtoken mask, segment mask
            for the context and each of response candidates separately.
        """

        if isinstance(batch[0], str):
            batch = [batch]

        samples = []
        for i in range(len(batch[0])):
            s = []
            for el in batch:
                s.append(el[i])
            samples.append(s)
        s_empt = [None] * len(samples[0])
        # TODO: add unique id
        examples = []
        for s in samples:
            ex = [InputExample(unique_id=0, text_a=text_a, text_b=text_b) for text_a, text_b in
                  zip(s, s_empt)]
            examples.append(ex)
        features = [convert_examples_to_features(el, self.max_seq_length, self.tokenizer) for el in examples]

        return features


@register('bert_sep_ranker_predictor_preprocessor')
class BertSepRankerPredictorPreprocessor(BertSepRankerPreprocessor):
    """Tokenize text to sub-tokens, encode sub-tokens with their indices, create tokens and segment masks for ranking.

    Builds features for a context and for each of the response candidates separately.
    In addition, builds features for a response (and corresponding context) text base.

    Args:
        resps: list of strings containing the base of text responses
        resp_vecs: BERT vector respresentations of `resps`, if is `None` features for the response base will be build
        conts: list of strings containing the base of text contexts
        cont_vecs: BERT vector respresentations of `conts`, if is `None` features for the response base will be build
    """

    def __init__(self,
                 resps=None, resp_vecs=None, conts=None, cont_vecs=None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.resp_features = None
        self.cont_features = None
        if resps is not None and resp_vecs is None:
            log.info("Building BERT features for the response base...")
            resp_batch = [[el] for el in resps]
            self.resp_features = self(resp_batch)
        if conts is not None and cont_vecs is None:
            log.info("Building BERT features for the context base...")
            cont_batch = [[el] for el in conts]
            self.cont_features = self(cont_batch)
