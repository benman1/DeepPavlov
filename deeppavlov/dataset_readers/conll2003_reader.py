from pathlib import Path
from logging import getLogger

from deeppavlov.core.common.registry import register
from deeppavlov.core.data.dataset_reader import DatasetReader
from deeppavlov.core.data.utils import download_decompress

log = getLogger(__name__)

@register('conll2003_reader')
class Conll2003DatasetReader(DatasetReader):
    """Class to read training datasets in CoNLL-2003 format"""

    def read(self,
             data_path: str,
             dataset_name: str = None,
             provide_pos: bool = False,
             provide_doc_ids: bool = False,
             iob: bool = False,
             docstart_token: str = None,
             max_seq_len: int = 512,
             step_size: int = 256):
        self.provide_pos = provide_pos
        self.provide_doc_ids = provide_doc_ids
        self.iob = iob
        self.docstart_token = docstart_token
        self.num_docs = 0
        self.x_is_tuple = self.provide_pos or self.provide_doc_ids
        data_path = Path(data_path)
        files = list(data_path.glob('*.txt'))
        if 'train.txt' not in {file_path.name for file_path in files}:
            if dataset_name == 'conll2003':
                url = 'http://files.deeppavlov.ai/deeppavlov_data/conll2003_v2.tar.gz'
            elif dataset_name == 'collection_rus':
                url = 'http://files.deeppavlov.ai/deeppavlov_data/collection3_v2.tar.gz'
            elif dataset_name == 'ontonotes':
                url = 'http://files.deeppavlov.ai/deeppavlov_data/ontonotes_ner.tar.gz'
            else:
                raise RuntimeError('train.txt not found in "{}"'.format(data_path))
            data_path.mkdir(exist_ok=True, parents=True)
            download_decompress(url, data_path)
            files = list(data_path.glob('*.txt'))
        dataset = {}

        for file_name in files:
            name = file_name.with_suffix('').name
            dataset[name] = self.parse_ner_file(file_name)
        return dataset

    def parse_ner_file(self, file_name: Path):
        def wrap_samples(x, tags, curr_samples=[]):
            if len(x) > self.max_seq_len:
                return wrap_samples(
                    x[self.step_size:],
                    tags[self.step_size:],
                    curr_samples+[(x[:self.max_seq_len], tags[:self.max_seq_len])]
                )
            else:
                return curr_samples+[(x, tags)]
        
        samples = []
        with file_name.open(encoding='utf8') as f:
            tokens = []
            pos_tags = []
            tags = []
            for line in f:
                # Check end of the document
                if 'DOCSTART' in line:
                    if len(tokens) > 1:
                        x = tokens if not self.x_is_tuple else (tokens,)
                        if self.provide_pos:
                            x = x + (pos_tags,)
                        if self.provide_doc_ids:
                            x = x + (self.num_docs,)
                        samples.extend(wrap_samples(x, tags))
                        tokens = []
                        pos_tags = []
                        tags = []
                    self.num_docs += 1
                    if self.docstart_token is not None:
                        tokens = [self.docstart_token]
                        pos_tags = ['O']
                        tags = ['O']
                elif len(line) < 2:
                    if (len(tokens) > 0) and (tokens != [self.docstart_token]):
                        x = tokens if not self.x_is_tuple else (tokens,)
                        if self.provide_pos:
                            x = x + (pos_tags,)
                        if self.provide_doc_ids:
                            x = x + (self.num_docs,)
                        samples.extend(wrap_samples(x, tags))
                        tokens = []
                        pos_tags = []
                        tags = []
                else:
                    if self.provide_pos:
                        try:
                            token, pos, *_, tag = line.split()
                            pos_tags.append(pos)
                        except:
                            log.warning('Skip {}, splitted as {}'.format(repr(line), repr(line.split())))
                            continue
                    else:
                        try:
                            token, *_, tag = line.split()
                        except:
                            log.warning('Skip {}, splitted as {}'.format(repr(line), repr(line.split())))
                            continue
                
                    tags.append(tag)
                    tokens.append(token)

            if tokens:
                x = tokens if not self.x_is_tuple else (tokens,)
                if self.provide_pos:
                    x = x + (pos_tags,)
                if self.provide_doc_ids:
                    x = x + (self.num_docs,)
                samples.extend(wrap_samples(x, tags))
                self.num_docs += 1
            
            if self.iob:
                return [(x, self._iob2_to_iob(tags)) for x, tags in samples]

        return samples

    @staticmethod
    def _iob2_to_iob(tags):
        iob_tags = []

        for n, tag in enumerate(tags):
            if tag.startswith('B-') and (not n or (tags[n - 1][2:] != tag[2:])):
                tag = tag.replace("B-", "I-")
            iob_tags.append(tag)

        return iob_tags
