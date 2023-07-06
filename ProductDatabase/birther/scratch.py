import idelib
doc = idelib.importFile("SSX00004.IDE")
accel = doc.channels[8].getSession()
mmm = accel.arrayMinMeanMax()
print(1)