# Copyright 2017 Sidewalk Labs | https://www.apache.org/licenses/LICENSE-2.0

from __future__ import (
    absolute_import, division, print_function, unicode_literals
)

import pandas as pd
import numpy as np
from collections import OrderedDict
import os
import logging

from doppelganger import marginals

FILE_PATTERN = 'state_{}_puma_{}_{}'
logging.basicConfig(filename='logs', filemode='a', level=logging.INFO)


class AccuracyException(Exception):
    pass


class Accuracy(object):
    def __init__(self, person_pums, household_pums, marginals,
                 generated_persons, generated_households):
        self.person_pums = person_pums
        self.household_pums = household_pums
        self.marginals = marginals
        self.generated_persons = generated_persons
        self.generated_households = generated_households

    @staticmethod
    def from_data_dir(state, puma, data_dir):
        '''Helper method for loading datafiles with same format output by download_allocate_generate
        run script

        Args:
            state: state id
            puma: puma id
            data_dir: directory with stored csv files

        Return: an initialized Accuracy object
        '''
        return Accuracy.from_csvs(
                state, puma,
                data_dir + os.path.sep + FILE_PATTERN.format(state, puma, 'persons_pums.csv'),
                data_dir + os.path.sep + FILE_PATTERN.format(state, puma, 'households_pums.csv'),
                data_dir + os.path.sep + FILE_PATTERN.format(state, puma, 'marginals.csv'),
                data_dir + os.path.sep + FILE_PATTERN.format(state, puma, 'people.csv'),
                data_dir + os.path.sep + FILE_PATTERN.format(state, puma, 'households.csv')
            )

    @staticmethod
    def from_csvs(
                state, puma,
                person_pums_filepath,
                household_pums_filepath,
                marginals_filepath,
                generated_persons_filepath,
                generated_households_filepath,
            ):
        '''Load csv files for use in accuracy calcs'''

        msg = '''Accuracy's from_data_dir Assumes files of the form:
            state_{state_id}_puma_{puma_id}_X
        Where X is contained in the set:
            {persons_pums.csv, households_pums.csv, marginals.csv, people.csv, households.csv}
        '''
        try:
            df_person = pd.read_csv(person_pums_filepath)
            df_household = pd.read_csv(household_pums_filepath)
            df_marginal = pd.read_csv(marginals_filepath)
            df_gen_persons = pd.read_csv(generated_persons_filepath)
            df_gen_households = pd.read_csv(generated_households_filepath)
        except IOError as e:
            logging.exception('{}\n{}'.format(msg, str(e)))
            raise IOError
        return Accuracy(df_person, df_household, df_marginal, df_gen_persons, df_gen_households)

    def _comparison_dataframe(self, marginal_variables=['all']):
        '''Helper to the metrics calls
        Args:
            variables (list(str)): list of marginal variables to compute error on. 'all' or ['all']
                will compute error on all eligible marginal variables
        Returns:
            dataframe with pums, marginal, and generated counts per variable
        '''

        variables = dict()
        if marginal_variables == 'all' or marginal_variables == ['all']:
            for control, bin_dict in marginals.CONTROLS.items():
                variables[control] = bin_dict.keys()
        else:
            for var in marginal_variables:
                variables[var] = marginals.CONTROLS[var].keys()

        # count should be its own marginal variable
        if 'num_people' in variables.keys():
            variables['num_people'].remove('count')

        d = OrderedDict()
        for variable, bins in variables.items():
            for bin in bins:
                d[(variable, bin)] = list()
                if variable == 'age':
                    d[(variable, bin)].append(
                        self.person_pums[self.person_pums[variable] == bin].person_weight.sum())
                    d[(variable, bin)].append(
                        self.generated_persons[self.generated_persons[variable] == bin]
                        .count()[0])
                elif variable == 'num_people':
                    d[(variable, bin)].append(self.household_pums[
                        self.household_pums[variable] == bin].household_weight.sum())
                    d[(variable, bin)].append(
                        self.generated_households[self.generated_households[variable] == bin]
                        .count()[0]
                    )
                elif variable == 'num_vehicles':
                    d[(variable, bin)].append(self.household_pums[
                        self.household_pums[variable] == bin].household_weight.sum())
                    d[(variable, bin)].append(
                        self.generated_households[self.generated_households[variable] == bin]
                        .count()[0]
                    )
                d[(variable, bin)].append(self.marginals[variable+'_'+bin].sum())
            # end bin
        # end variable

        return pd.DataFrame(d.values(), index=d.keys(), columns=['pums', 'gen', 'marginal'])

    def root_mean_squared_error(self, variables=['all']):
        '''Root mean squared error of the pums-marginals and generated-marginals vectors.
        No verbose option available due to the mean as an inner operation.
        Please use mean_root_squared_error for a verbose analog
        '''
        df = self._comparison_dataframe(variables)
        return (
                np.sqrt(np.mean(np.square(df.pums - df.marginal))),
                np.sqrt(np.mean(np.square(df.gen - df.marginal)))
            )

    def mean_root_squared_error(self, variables=['all'], verbose=False):
        '''Similar to rmse, but taking the mean at the end so that the error of individual variables
        can be analyzed if verbose is set to True
        '''
        df = self._comparison_dataframe(variables)
        baseline = np.sqrt(np.square(df.pums - df.marginal))
        doppel = np.sqrt(np.square(df.gen - df.marginal))

        df = pd.DataFrame([baseline, doppel]).transpose()
        df.columns = ['marginal-pums', 'marginal-doppelganger']
        if verbose:
            print(df)
            logging.info(df)
        return np.mean(baseline), np.mean(doppel)

    def mean_absolute_pct_error(self, variables=['all'], verbose=False):
        '''Accuracy in Mean Absolute %Diff'''
        df = self._comparison_dataframe(variables)
        baseline = np.abs(df.pums - df.marginal)/((df.pums + df.marginal)/2)
        doppel = np.abs(df.gen - df.marginal)/((df.gen + df.marginal)/2)

        df = pd.DataFrame([baseline, doppel]).transpose()
        df.columns = ['marginal-pums', 'marginal-doppelganger']
        if verbose:
            print(df)
            logging.info(df)
        return np.mean(baseline), np.mean(doppel)

    @staticmethod
    def run_pumas(state_puma, data_dir,
                  variables=['all'], statistic='mean_absolute_pct_error', verbose=False):
        '''Helper method to run an accuracy stats for multiple pumas
        Args:
            state_puma (dict): dictionary of state to puma list within the state.
            data_dir (str): directory with stored data in the form put out by
                download_allocate_generate
            E.g. load 3 Kansan (20) pumas and 2 in Missouri (29)
                state_puma['20'] = ['00500', '00602', '00604']
                state_puma['29'] = ['00901', '00902']
            variables (list(str)): vars to run error on. must be defined in marginals.py
            statistic (str): must be an implemented error statistic:
                mean_absolute_pct_error, root_mean_squared_error, mean_root_squared_error
            verbose (boolean): display per-variable error
        '''
        d_result = OrderedDict()
        for state, pumas in state_puma.items():
            for puma in pumas:
                if verbose:
                    print(' '.join(['\nrun accuracy:', state, puma]))
                    logging.info(' '.join(['\nrun accuracy:', state, puma]))
                accuracy = Accuracy.from_data_dir(state, puma, data_dir)
                if statistic == 'mean_absolute_pct_error':
                    d_result[(state, puma)] = accuracy.mean_absolute_pct_error(variables, verbose)
                elif statistic == 'mean_root_squared_error':
                    d_result[(state, puma)] = accuracy.mean_root_squared_error(variables, verbose)
                elif statistic == 'root_mean_squared_error':
                    d_result[(state, puma)] = accuracy.root_mean_squared_error(variables)
                else:
                    msg = 'Accuracy statistic not recognized'
                    logging.exception(msg)
                    raise AccuracyException()

        df = pd.DataFrame(d_result.values(), index=d_result.keys(),
                          columns=['marginal-pums', 'marginal-doppelganger'])
        print('\nPUMA Totals')
        logging.info('\nPUMA Totals')
        logging.info(df)
        logging.info(df.mean())
        return df
