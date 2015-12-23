from sklearn import linear_model as lm
from sklearn.metrics import mean_absolute_error as mae
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
import config.SUTConfig as sut

__author__ = 'francesco'

class HTLinearModel:
    # Estimate multivariate linear regression model for each physical CPU and compute CPU productivity.
    # Parameters:
    #   - Ci_instr: sum of CPUi_(thread i) instructons, where i belongs to physical CPU Ci
    #   - Ci_td2 = sum of CPUi_cpu_clk_unhalted_thread - CPUi_cpu_clk_unhalted_thread_any, where i belongs to physical CPU Ci => clock cycles with Thread Density 2
    #   - Ci_td1: CPUi_cpu_clk_unhalted_thread_any - Ci_td2 => clock cycles with Thread Density 1
    #
    # Unknowns (Multivariate Linear Regression coefficients):
    #   - IPC_td1
    #   - IPC_td2 (= IPC_td1 * S, with S = Speedup w.r.t. IPC_td1)
    #
    # Equation:
    #   Ci_instr = IPC_td1 * Ci_td1 + IPC_td2 * Ci_td2
    #
    # To compute CPU productivity we need the max number of instructions with td2.
    #   - Ci_instr_max = Nominal CPU Frequency * IPC_td2
    #   - Ci_productivity = Ci_instr / Ci_instr_max
    #
    # Finally we compute Sys_mean_productivity as the global system mean of all Ci_productivity
    #
    # We can then correlate the run throughput with productivity and run utilization, plotting graphs and computing R^2

    test_name = ''

    Ci_td1 = {}
    Ci_td2 = {}
    Ci_instr = {}

    linear_model = {}
    Ci_instr_max = {}
    Ci_productivity = {}
    Sys_mean_productivity = pd.Series()

    Ci_IPC_max_td_max = {}
    Sys_mean_IPC_td_max = pd.Series()
    Sys_mean_estimated_IPC = pd.Series()

    Ci_atd = {}
    Sys_mean_atd = {}

    Ci_cbt = {}
    Sys_mean_cbt = {}

    Ci_frequency = {}
    Sys_mean_frequency = pd.Series()

    def estimate(self, dataset, test_name):
        self.test_name = test_name

        if not sut.CPU_HT_ACTIVE: # Hyperthreading OFF
            self.Ci_td1 = self.compute_td1(dataset)
            self.Ci_instr = self.compute_instr(dataset)

            self.linear_model = self.estimate_IPCs(self.Ci_td1, self.Ci_instr)
        else : # Hyperthreading ON
            self.Ci_td2 = self.compute_td2(dataset)
            self.Ci_td1 = self.compute_td1(dataset, self.Ci_td2)
            self.Ci_instr = self.compute_instr(dataset)

            self.linear_model = self.estimate_IPCs(self.Ci_td1, self.Ci_instr, self.Ci_td2)

        # print(Ci_td2['S0-C0'])
        # print(Ci_td2)
        # print(Ci_instr['S0-C0'])

        self.Ci_instr_max = self.compute_instr_max(self.linear_model)
        self.Ci_productivity = self.compute_productivity(self.Ci_instr, self.Ci_instr_max)
        self.Sys_mean_productivity = self.compute_sys_mean_productivity(self.Ci_productivity)

        # print(linear_model['S0-C0'])
        # print(Ci_instr_max['S0-C0'])
        # print(Ci_productivity)
        # print(Sys_mean_productivity)

        self.Ci_IPC_max_td_max = self.compute_IPC_at_run_with_td_max(dataset, sut.START_RUN, sut.END_RUN)
        self.Sys_mean_IPC_td_max = self.compute_sys_mean_IPC_at_td_max(self.Ci_IPC_max_td_max)
        self.Sys_mean_estimated_IPC = self.compute_sys_mean_estimated_IPC(self.linear_model)

        # print(Ci_max_IPC_td_max)
        # print(Sys_max_IPC_td_max)
        # print(Sys_mean_estimated_IPC)

        if not sut.CPU_HT_ACTIVE: # Hyperthreading OFF
            self.Ci_atd = self.compute_atd(dataset, self.Ci_td1)
        else : # Hyperthreading ON
            self.Ci_atd = self.compute_atd(dataset, self.Ci_td1, self.Ci_td2)

        self.Sys_mean_atd = self.compute_sys_mean_atd(self.Ci_atd)

        # print(Ci_atd)
        # print(Sys_mean_atd)

        self.Ci_cbt = self.compute_core_busy_time(dataset)
        self.Sys_mean_cbt = self.compute_sys_mean_core_busy_time(self.Ci_cbt)

        # print(Ci_cbt)
        # print(Sys_mean_cbt)

        self.Ci_frequency = self.compute_mean_frequencies(dataset)
        self.Sys_mean_frequency = self.compute_sys_mean_frequency(self.Ci_frequency)

        # Export csv file with plotted data
        self.gen_csv(dataset, self.linear_model, self.Ci_IPC_max_td_max,
                     self.Sys_mean_productivity, self.Sys_mean_atd, self.Sys_mean_cbt,
                     self.Sys_mean_frequency, self.Sys_mean_IPC_td_max, self.Sys_mean_estimated_IPC)

        return self # In order to chain estimate() with class constructor

    # For each Socket and for each Core i in Socket, calculate Ci_td2
    def compute_td2(self, dataset):
        result = {}
        for s in range(sut.CPU_SOCKETS):
            for c in range(sut.CPU_PHYSICAL_CORES_PER_SOCKET):
                tmp_td2 = pd.Series()

                for j in sut.CPU_PHYSICAL_TO_LOGICAL_CORES_MAPPING['CPU' + str(c)]:
                    if len(tmp_td2) == 0:
                        tmp_td2 = tmp_td2.append(dataset['perf-stats']['mean']['CPU' + str(j) + '_cpu_clk_unhalted_thread'])
                    else:
                        tmp_td2 = tmp_td2.add(dataset['perf-stats']['mean']['CPU' + str(j) + '_cpu_clk_unhalted_thread'])

                # Calculate Ci_td2 using unhalted clocks of the first logical core of cpu c
                result['S' + str(s) + '-C' + str(c)]  = tmp_td2.sub(dataset['perf-stats']['mean']['CPU' + str(sut.CPU_PHYSICAL_TO_LOGICAL_CORES_MAPPING['CPU' + str(c)][0]) + '_cpu_clk_unhalted_thread_any'])
        return result

    # For each Socket and for each Core i in Socket, calculate Ci_td1
    def compute_td1(self, dataset, Ci_td2=None):
        result = {}
        for s in range(sut.CPU_SOCKETS):
            for c in range(sut.CPU_PHYSICAL_CORES_PER_SOCKET):
                tmp_td1 = dataset['perf-stats']['mean']['CPU' + str(sut.CPU_PHYSICAL_TO_LOGICAL_CORES_MAPPING['CPU' + str(c)][0]) + '_cpu_clk_unhalted_thread_any'].copy()

                if Ci_td2 == None:
                    result['S' + str(s) + '-C' + str(c)] = tmp_td1
                else:
                    result['S' + str(s) + '-C' + str(c)] = tmp_td1.sub(Ci_td2['S' + str(s) + '-C' + str(c)])
        return result

    # For each Socket and for each Core i in Socket, calculate Ci_instr
    def compute_instr(self, dataset):
        result = {}
        for s in range(sut.CPU_SOCKETS):
            for c in range(sut.CPU_PHYSICAL_CORES_PER_SOCKET):
                tmp_instr = pd.Series()

                for j in sut.CPU_PHYSICAL_TO_LOGICAL_CORES_MAPPING['CPU' + str(c)]:
                    if len(tmp_instr) == 0:
                        tmp_instr = tmp_instr.append(dataset['perf-stats']['mean']['CPU' + str(j) + '_instructions'])
                    else:
                        tmp_instr = tmp_instr.add(dataset['perf-stats']['mean']['CPU' + str(j) + '_instructions'])

                result['S' + str(s) + '-C' + str(c)]  = tmp_instr.copy()
        return result

    # For each Socket and for each Core i in Socket, compute IPC_td1 and IPC_td2 with Multivariate Linear Regression
    def estimate_IPCs(self, Ci_td1, Ci_instr, Ci_td2=None):
        result = {}
        for s in range(sut.CPU_SOCKETS):
            for c in range(sut.CPU_PHYSICAL_CORES_PER_SOCKET):
                # y = one element per row [Ci_istr]
                y = np.array(Ci_instr['S' + str(s) + '-C' + str(c)])
                y = y.reshape(len(y), 1)

                if Ci_td2 == None:
                    X = [[i] for i in Ci_td1['S' + str(s) + '-C' + str(c)]]
                else:
                    # X = two elems per row [Ci_td1, Ci_td2]
                    X = [[i, j] for i, j in zip(Ci_td1['S' + str(s) + '-C' + str(c)], Ci_td2['S' + str(s) + '-C' + str(c)])]

                regr = lm.LinearRegression(fit_intercept=False) # fit_intercept=False is equivalent to "+ 0" in R
                regr.fit(X, y)
                result['S' + str(s) + '-C' + str(c)] = {'model' : regr, 'coefficients': regr.coef_}
                # print(regr.coef_)
                # print(result)
        return result

    # For each Socket and for each Core i in Socket, compute Ci_instr_max at td1 and td2
    def compute_instr_max(self, linear_model):
        result = {}
        for s in range(sut.CPU_SOCKETS):
            for c in range(sut.CPU_PHYSICAL_CORES_PER_SOCKET):
                # result['S' + str(s) + '-C' + str(c)] = sut.CPU_NOMINAL_FREQUENCY * linear_model['S' + str(s) + '-C' + str(c)]['coefficients']
                result['S' + str(s) + '-C' + str(c)] = sut.CPU_ACTUAL_MAX_FREQUENCY * linear_model['S' + str(s) + '-C' + str(c)]['coefficients']

        return result

    # For each Socket and for each Core i in Socket, compute Productivity as Ci_instr / Ci_instr_max during each time interval
    # If Hyperthreading ON, compute Productivity w.r.t. td2
    # If Hyperthreading OFF, compute Productivity w.r.t. td1
    def compute_productivity(self, Ci_instr, Ci_instr_max):
        result = {}
        for s in range(sut.CPU_SOCKETS):
            for c in range(sut.CPU_PHYSICAL_CORES_PER_SOCKET):
                result['S' + str(s) + '-C' + str(c)] = Ci_instr['S' + str(s) + '-C' + str(c)] / Ci_instr_max['S' + str(s) + '-C' + str(c)][0][sut.CPU_HT_ACTIVE]

        return result

    # Compute the system global mean of Ci_productivity
    def compute_sys_mean_productivity(self, Ci_productivity):
        result = pd.Series(name='Sys_mean_productivity')
        for s in range(sut.CPU_SOCKETS):
            for c in range(sut.CPU_PHYSICAL_CORES_PER_SOCKET):
                if len(result) == 0:
                    result = result.append(Ci_productivity['S' + str(s) + '-C' + str(c)])
                else:
                    result = result.add(Ci_productivity['S' + str(s) + '-C' + str(c)])

        result = result / sut.CPU_PHYSICAL_CORES
        result.name = "Sys_mean_productivity"
        return result

    # Compute Average Thread Density
    # Ci_atd = Ci_td1 / cpu_clk_unhalted_thread_any + 2 * Ci_td2 / cpu_clk_unhalted_thread_any
    def compute_atd(self, dataset, Ci_td1, Ci_td2=None):
        result = {}
        for s in range(sut.CPU_SOCKETS):
            for c in range(sut.CPU_PHYSICAL_CORES_PER_SOCKET):
                tmp_atd = Ci_td1['S' + str(s) + '-C' + str(c)].copy()
                # Calculate using unhalted clocks of the first logical core of cpu c
                tmp_atd = tmp_atd.div(dataset['perf-stats']['mean']['CPU' + str(sut.CPU_PHYSICAL_TO_LOGICAL_CORES_MAPPING['CPU' + str(c)][0]) + '_cpu_clk_unhalted_thread_any'])

                if Ci_td2 != None:
                    tmp_td2 = Ci_td2['S' + str(s) + '-C' + str(c)].div(dataset['perf-stats']['mean']['CPU' + str(sut.CPU_PHYSICAL_TO_LOGICAL_CORES_MAPPING['CPU' + str(c)][0]) + '_cpu_clk_unhalted_thread_any']) \
                        .multiply(2)
                    tmp_atd = tmp_atd.add(tmp_td2)

                result['S' + str(s) + '-C' + str(c)] = tmp_atd

        return result

    # Compute the system global mean of Ci_atd
    def compute_sys_mean_atd(self, Ci_atd):
        result = pd.Series(name='Sys_mean_atd')
        for s in range(sut.CPU_SOCKETS):
            for c in range(sut.CPU_PHYSICAL_CORES_PER_SOCKET):
                if len(result) == 0:
                    result = result.append(Ci_atd['S' + str(s) + '-C' + str(c)])
                else:
                    result = result.add(Ci_atd['S' + str(s) + '-C' + str(c)])

        result = result / sut.CPU_PHYSICAL_CORES
        result.name = "Sys_mean_atd"
        return result

    # Compute the core busy time (C0 state residency)
    # Ci_cbt = cpu_clk_unhalted.ref_tsc / CPU_NOMINAL_FREQUENCY (that is TSC ?)
    def compute_core_busy_time(self, dataset):
        result = {}
        for s in range(sut.CPU_SOCKETS):
            for c in range(sut.CPU_PHYSICAL_CORES_PER_SOCKET):
                tmp_ref_tsc = pd.Series()

                for j in sut.CPU_PHYSICAL_TO_LOGICAL_CORES_MAPPING['CPU' + str(c)]:
                    if len(tmp_ref_tsc) == 0:
                        tmp_ref_tsc = tmp_ref_tsc.append(dataset['perf-stats']['mean']['CPU' + str(j) + '_cpu_clk_unhalted_ref_tsc'])
                    else:
                        tmp_ref_tsc = tmp_ref_tsc.add(dataset['perf-stats']['mean']['CPU' + str(j) + '_cpu_clk_unhalted_ref_tsc'])

                tmp_ref_tsc = tmp_ref_tsc.div(sut.CPU_THREADS_PER_CORE)
                result['S' + str(s) + '-C' + str(c)] = tmp_ref_tsc.div(sut.CPU_NOMINAL_FREQUENCY)
        return result

    # Compute the system global mean of Ci_cbt
    def compute_sys_mean_core_busy_time(self, Ci_cbt):
        result = pd.Series(name='Sys_mean_cbt')
        for s in range(sut.CPU_SOCKETS):
            for c in range(sut.CPU_PHYSICAL_CORES_PER_SOCKET):
                if len(result) == 0:
                    result = result.append(Ci_cbt['S' + str(s) + '-C' + str(c)])
                else:
                    result = result.add(Ci_cbt['S' + str(s) + '-C' + str(c)])

        result = result / sut.CPU_PHYSICAL_CORES
        result.name = "Sys_mean_cbt"
        return result

    # For each Socket and for each Core i in Socket, calculate real IPC at TD depending on the specified run
    def compute_IPC_at_run_with_td_max(self, dataset, startRun, endRun):
        startRun = startRun - 1

        result = {}

        # Compute and sort positions to be changed
        positions = [i + 10 * times for i in range(startRun, endRun) for times in range(sut.NUM_TESTS)]
        positions.sort()

        for s in range(sut.CPU_SOCKETS):
            for c in range(sut.CPU_PHYSICAL_CORES_PER_SOCKET):
                result['S' + str(s) + '-C' + str(c)] = pd.Series([0 for i in range(len(dataset['perf-stats']['mean']))], dtype=float) # Set all to zero

                for i in positions:
                    for j in sut.CPU_PHYSICAL_TO_LOGICAL_CORES_MAPPING['CPU' + str(c)]:
                        result['S' + str(s) + '-C' + str(c)][i] = result['S' + str(s) + '-C' + str(c)][i] + dataset['perf-stats']['mean']['CPU' + str(j) + '_instructions'][i]

                    # Calculate IPC at TD max using unhalted clocks of the first logical core of cpu c
                    result['S' + str(s) + '-C' + str(c)][i] = result['S' + str(s) + '-C' + str(c)][i] / dataset['perf-stats']['mean']['CPU' + str(sut.CPU_PHYSICAL_TO_LOGICAL_CORES_MAPPING['CPU' + str(c)][0]) + '_cpu_clk_unhalted_thread'][i]

        return result

    # Compute the system global mean of Ci_max_IPC_td_max
    def compute_sys_mean_IPC_at_td_max(self, Ci_IPC_max_td_max):
        result = pd.Series(name='Sys_mean_IPC')
        for s in range(sut.CPU_SOCKETS):
            for c in range(sut.CPU_PHYSICAL_CORES_PER_SOCKET):
                if len(result) == 0:
                    result = result.append(Ci_IPC_max_td_max['S' + str(s) + '-C' + str(c)])
                else:
                    result = result.add(Ci_IPC_max_td_max['S' + str(s) + '-C' + str(c)])

        result = result / sut.CPU_PHYSICAL_CORES
        result.name = "Sys_mean_IPC"
        return result

    # Compute the system global mean of estimated IPC
    # If HT is ON then the mean uses IPC estimation at TD = 2
    # If HT is OFF then the mean uses IPC estimation at TD = 1
    def compute_sys_mean_estimated_IPC(self, linear_model):
        result = pd.Series(name='Sys_mean_estimated_IPC_TD' + str(2 if sut.CPU_HT_ACTIVE else 1))

        inserted = False
        index = 0

        for s in range(sut.CPU_SOCKETS):
            for c in range(sut.CPU_PHYSICAL_CORES_PER_SOCKET):
                if not inserted :
                    result = result.set_value(index, linear_model['S' + str(s) + '-C' + str(c)]['coefficients'][0][sut.CPU_HT_ACTIVE])
                    inserted = True
                else:
                    result[index] = result[index] + linear_model['S' + str(s) + '-C' + str(c)]['coefficients'][0][sut.CPU_HT_ACTIVE]
            index += 1
            inserted = False

        result = result / sut.CPU_PHYSICAL_CORES
        result.name = "Sys_mean_estimated_IPC_TD" + str(2 if sut.CPU_HT_ACTIVE else 1)
        return result

    # Compute the mean frequencies for each core
    # frequency = (cpu_clk_unhalted_thread / cpu_clk_unhalted.ref_tsc) * CPU_NOMINAL_FREQUENCY
    def compute_mean_frequencies(self, dataset):
        result = {}

        for s in range(sut.CPU_SOCKETS):
            for c in range(sut.CPU_PHYSICAL_CORES_PER_SOCKET):
                tmp_freq = pd.Series()
                tmp_ref_tsc = pd.Series()

                for j in sut.CPU_PHYSICAL_TO_LOGICAL_CORES_MAPPING['CPU' + str(c)]:
                    if len(tmp_freq) == 0 and len(tmp_ref_tsc) == 0:
                        tmp_freq = tmp_freq.append(dataset['perf-stats']['mean']['CPU' + str(j) + '_cpu_clk_unhalted_thread'])
                        tmp_ref_tsc = tmp_ref_tsc.append(dataset['perf-stats']['mean']['CPU' + str(j) + '_cpu_clk_unhalted_ref_tsc'])
                    else:
                        tmp_freq = tmp_freq.add(dataset['perf-stats']['mean']['CPU' + str(j) + '_cpu_clk_unhalted_thread'])
                        tmp_ref_tsc = tmp_ref_tsc.add(dataset['perf-stats']['mean']['CPU' + str(j) + '_cpu_clk_unhalted_ref_tsc'])

                # Divide by number of threads per core
                tmp_freq = tmp_freq.div(sut.CPU_THREADS_PER_CORE)
                tmp_ref_tsc = tmp_ref_tsc.div(sut.CPU_THREADS_PER_CORE)

                result['S' + str(s) + '-C' + str(c)] = tmp_freq.div(tmp_ref_tsc).multiply(sut.CPU_NOMINAL_FREQUENCY)

        return result

    # Compute the system global frequency mean
    def compute_sys_mean_frequency(self, Ci_frequency):
        result = pd.Series(name='Sys_mean_FREQ')
        for s in range(sut.CPU_SOCKETS):
            for c in range(sut.CPU_PHYSICAL_CORES_PER_SOCKET):
                if len(result) == 0:
                    result = result.append(Ci_frequency['S' + str(s) + '-C' + str(c)])
                else:
                    result = result.add(Ci_frequency['S' + str(s) + '-C' + str(c)])

        result = result / sut.CPU_PHYSICAL_CORES
        result.name = "Sys_mean_FREQ"

        return result

    # Generate csv file with graph data
    def gen_csv(self, dataset, linear_model, Ci_max_IPC_td_max, *args):
        df = pd.DataFrame()
        df = df.append(dataset['runs']['TotClients'])
        df = df.append(dataset['runs']['XavgTot'])
        df = df.append(dataset['runs']['UavgTot'])
        df = df.append(dataset['runs']['RavgTot'])

        for i in args:
            df = df.append(i) # Each Pandas Series must have a name setted! e.g. result.name = "myname"

        df = df.T

        # After the transposition, add columns
        # Print estimated IPC and computed real IPC
        for s in range(sut.CPU_SOCKETS):
            for c in range(sut.CPU_PHYSICAL_CORES_PER_SOCKET):
                df['S' + str(s) + '-C' + str(c) + '-EST-IPC-TD1'] = linear_model['S' + str(s) + '-C' + str(c)]['coefficients'][0][0]

                if sut.CPU_HT_ACTIVE: # Hyperthreading ON
                    df['S' + str(s) + '-C' + str(c) + '-EST-IPC-TD2'] = linear_model['S' + str(s) + '-C' + str(c)]['coefficients'][0][1]

                df['S' + str(s) + '-C' + str(c) + '-REAL-IPC-TD' + str(2 if sut.CPU_HT_ACTIVE else 1)] = Ci_max_IPC_td_max['S' + str(s) + '-C' + str(c)]

        df.to_csv(sut.OUTPUT_DIR + '/' + self.test_name + '/LRModel.csv', sep=';')