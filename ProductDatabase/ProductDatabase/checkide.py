"""
Sensor Validity Program; Checks existence, time length, sample rate, and value range of all channels
'NO DATA EXISTS' - Channel has no data
('VALUE RANGE FAILURE', [List of sub channel IDs that fail the value range] )
'DURATION LENGTH FAILURE' - Channel stops or starts after 5 seconds of the lowest start/end time of a channel
'SAMPLE RATE FAILURE' - Block(s) within the channel are > 1% away from the average channel sample rate
"""

import idelib
from functools import singledispatch
from collections import defaultdict
from defvalues import defRates


def checkIde(fileread, expectedVals, blocksOutput=None):
    """Check if the sensor is reading & the data is valid
    :param fileread: str IDEfile path
    :param expectedVals: dict of {channel id: dict of ranges, sample rate}
    :param blocksOutput: string Outputfile path for block failures
    :return: dict of {failing channel IDs: list of errors}
    """

    with idelib.importFile(fileread) as ds:

        checkIde.problems = defaultdict(list)

        # BEGIN LENGTH PROCESS
        duration = getLengthInterval(ds.channels.values())

        for ch in ds.channels.values():
            sesh = ch.getSession()
            if sesh:  # CHANNEL'S EXISTENCE SUCCEEDS
                # Determine if a comparison rate is given
                compRate = None
                if str(ch.id) in expectedVals and "sample_rate" in expectedVals[str(ch.id)]:
                    compRate = expectedVals[str(ch.id)]["sample_rate"]
                elif str(ch.id) in defRates or compRate:
                    compRate = defRates[str(ch.id)]

                checkRate(sesh, ch.id, checkIde.problems, compRate, blocksOutput)  # SAMPLE RATE TEST
                checkDuration(duration[0], duration[1], sesh, checkIde.problems)  # LENGTH

                # VALUE RANGE
                if str(ch.id) in expectedVals:
                    if "range" in expectedVals[str(ch.id)]:
                        rangeCheck(expectedVals[str(ch.id)]["range"], ch, checkIde.problems)

            else:  # EXISTENCE FAILS
                checkIde.problems[str(ch.id)] = ["NO DATA EXISTS"]

    return len(checkIde.problems) == 0, dict(checkIde.problems)


def checkDuration(startMax, endMax, sesh, problems):
    """Considers if the channel duration is appropriate
    :param startMax: int (minimum channel start time + 5 seconds)
    :param endMax: int (minimum channel end time + 5 seconds)
    :param sesh: idelib.dataset.EventArray (channel session)
    :param problems: dict {channel id: list of errors}
    """
    timeErrors = []
    if sesh.getInterval()[0] > startMax:
        timeErrors.append(f"Start Time {sesh.getInterval()[0]} should be < {startMax}")

    if sesh.getInterval()[1] > endMax:
        timeErrors.append(f"End Time {sesh.getInterval()[1]} should be < {endMax}")

    if timeErrors:
        problems[str(sesh._data[0].channelID)].append(("DURATION FAILURE: \n", {timeErrors}))


def checkRate(sesh, chId, problems, compRate, blocksOutput=None):
    """Considers if the sample rate of each block within 1% of the channel's average sample rate
    :param sesh: idelib.dataset.EventArray (channel session)
    :param chId: int (channel ID#)
    :param problems: dict {channel id: list of errors}
    :param compRate: None, int (a sample rate to compare blocks to), or function (a separate rate checking function)
    :param blocksOutput: None, str (output file path for block fails)
    """

    if hasattr(compRate, '__call__'):  # if a function is provided for rate comparison, do not use checkRate
        compRate(sesh, chId, problems)
        return

    if len(sesh._data) > 1 and chId != 36:
        if not compRate:  # compRate will be the average channel sample rate
            compRate = getRate((len(sesh) - sesh._data[0].numSamples - sesh._data[-1].numSamples),
                               sesh._data[-2].endTime, sesh._data[1].startTime)
        end = len(sesh._data) - 1
    elif len(sesh._data) == 1 and compRate:
        end = 1
    elif chId != 36:  # 1 block & no comparison rate
        return

    if chId != 36:
        blockFails = {}  # dict of << failing block#, str of block rate >>

        for i in range(0, end):  # through 1-2nd to last blocks only
            bkRate = getRate(sesh._data[i].numSamples, sesh._data[i].endTime, sesh._data[i].startTime)
            diffToComp = getDiff(bkRate, compRate)

            if diffToComp > 0.01 and i != 0:
                blockFails[f"{i}"] = f"{bkRate:.3f} Hz, {(diffToComp * 100):.3f}%"
            elif diffToComp > 0.035:
                blockFails[f"{i}"] = f"{bkRate:.3f} Hz, {(diffToComp * 100):.3f}%"

        if blockFails and not blocksOutput:
            problems[str(chId)].append((f"SAMPLE RATE FAIlURE: Expected: {compRate:.3f}Hz", blockFails))
        elif blockFails and blocksOutput:
            problems[str(chId)].append((f"SAMPLE RATE FAIlURE:", f"Open {blocksOutput}"))
            outfileBlocks(blockFails, chId, blocksOutput)

        checkMissingBlock(sesh._data, compRate, chId, problems, blockFails)

    else:  # Ch36
        avgRate = getRate((len(sesh) - sesh._data[0].numSamples - sesh._data[-1].numSamples),
                          sesh._data[-2].endTime, sesh._data[1].startTime)
        diffToComp = getDiff(avgRate, compRate)  # compare avg to 1 Hz
        if diffToComp > 0.01:
            problems[str(chId)].append((f"SAMPLE RATE FAILURE: Expected: {compRate:.3f} Hz, ",
                                       f"Actual: {compRate:.3f} Hz (Diff of {diffToComp:.3f})"))
        checkMissingBlock(sesh._data, compRate, chId, problems)


def checkMissingBlock(seshData, compRate, chId, problems, blockFails=()):
    """Check if a block of data has been skipped
    :param seshData: list (channel blocks list)
    :param compRate: int (sample rate tp compare to)
    :param chId: number of channel
    :param problems: dict {channel id: list of errors}
    :param blockFails: dict {failing blocks: rates}
    """

    missingBlocks = []
    timeDiffs = []
    for i in range(int(chId == 36), len(seshData) - 2):  # comparing sets of two blocks

        rate = getRate(seshData[i].numSamples + seshData[i + 1].numSamples, seshData[i + 1].endTime,
                       seshData[i].startTime)
        diff = getDiff(rate, compRate)
        if diff > 0.03:
            if str(i) not in blockFails:
                missingBlocks.append(
                    f'BLOCK MISSING AT {i} - {i}-{i + 1} Rate is {(diff * 100):.3f}% of Avg.')
        timeDiffs.append(seshData[i + 1].startTime - seshData[i].endTime)

    if missingBlocks:
        problems[str(chId)].append(("SAMPLE RATE FAILURE: ", missingBlocks))


def getLengthInterval(channels):
    """Find the maximum allowed start and end time
    :param channels: idelib.dataset
    :return: tuple (minimum allowed start time, minimum allowed end time)
    """
    # BEGIN LENGTH PROCESS BY STORING ALL CHANNELS STARTS AND ENDS
    endTimes = []
    startTimes = []

    # get the starts and ends of all
    for ch in channels:
        sesh = ch.getSession()
        if sesh:
            endTimes.append(sesh.getInterval()[1])
            startTimes.append(sesh.getInterval()[0])

    # DETERMINE 5 SECONDS FROM START AND END FOR LENGTH TEST
    return min(startTimes) + 5e+6, min(endTimes) + 5e+6


@singledispatch
def rangeCheck(rg, ch, problems):
    """Check the specific ranges in the list/tuple against the appropriate sub channel
    :param rg: list or tuple with channel's value range
    :param ch: idelib.dataset (channel)
    :param problems: dict {channel ID: list of errors}
    """
    failedSubs = {}

    for sch in ch.subchannels:
        if sch.getSession().getMin()[1] < rg[0] or sch.getSession().getMax()[1] > rg[1]:
            failedSubs[str(sch.id)] = f"Actual Range: " \
                                      f"({sch.getSession().getMin()[1]}, {sch.getSession().getMax()[1]})"
    if failedSubs:
        problems[str(ch.id)].append((f"VALUE FAILURE: Expected Range: {rg}", failedSubs))


@rangeCheck.register(dict)
def _(rangeDict, ch, problems):
    """Check the specific ranges in the dict against the appropriate sub channel
    :param rangeDict: dict {sub channel: list or tuple of range}
    :param ch: idelib.dataset (channel)
    :param problems: dict {channel id: list of errors}
    """
    failedSubs = {}

    for schKey, rg in rangeDict.items():
        sch = ch.getSubChannel(int(schKey)).getSession()
        if sch.getMin()[1] < rg[0] or sch.getMax()[1] > rg[1]:
            failedSubs[str(schKey)] = f"Expected Range: {rg}, Actual Range: ({sch.getMin()[1]}, {sch.getMax()[1]})"

    if failedSubs:
        problems[str(ch.id)].append(("VALUE RANGE FAILURE", failedSubs))


def outfileBlocks(fails, chId, file):
    """ Write each failure in fails to the file
    :param fails: dict of 'block id': (rate, % difference)
    :param chId: int (channel ID)
    :param file: str of file to print to
    """

    with open(file, "+a") as outfile:
        outfile.write(f"\nChannel {chId} Block Failures:\n")
        for block, val in fails.items():
            outfile.write(f"{block}: {val}\n")


def getDiff(rateOf, rateTo):
    """Find percent diff between two rates
    :param rateOf: int sample rate
    :param rateTo: int sample rate
    :return: int (percent difference between the two rates)
    """
    return abs((rateOf - rateTo) / rateTo)


def getRate(size, end, start):
    """Find sample rate
    :param size: int (number of samples)
    :param end: int (end time)
    :param start: int (start time)
    :return: int (sample rate)
    """
    return (size - 1) * 1e+6 / (end - start)


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description='Check IDE Recording Validity')
    parser.add_argument('IDEfile', type=str, help="name of IDE file to be checked")
    parser.add_argument('-e', '--expectedvalues', required=False,
                        help="name of .json file with dictionary of expected channel ranges & sample rates")
    parser.add_argument('-o', '--outputfile', type=str, required=False,
                        help="name of .txt file to output blocks failing the rate test")
    args = parser.parse_args()

    if args.expectedvalues:
        with open(args.expectedvalues, 'r') as openfile:
            args.expectedvalues = json.load(openfile)

    else:
        args.expectedvalues = {}  # "default" separated

    results = checkIde(args.IDEfile, args.expectedvalues, args.outputfile)

    if results[0]:
        print("Tests passed!")
    else:
        for key, value in results[1].items():
            print(f"Channel {key}: {value}", end="\n")
