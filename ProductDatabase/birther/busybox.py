"""
Little module defining a specialized 'busy' dialog that displays until
something happens or it times out.

Created on Sep 20, 2019

@author: dstokes


FUTURE: Reuse `BusyBox`. It's been written to be more general-purpose than
the equivalent in the Slam Stick Lab firmware updater.
"""

import os.path
import time

import wx
from wx.adv import Animation, AnimationCtrl

# Note: This bit isn't reusable elsewhere.
import paths
RESOURCES_PATH = paths.RESOURCES_PATH


#===============================================================================
# 
#===============================================================================

class BusyBox(wx.Dialog):
    """ A generic modal dialog that waits for something to happen. 
    """
    
    # Values returned by `ShowModal()`. `ID_CANCEL` is duplicated just to
    # make things tidy (all IDs in the same place).
    ID_CANCEL = wx.ID_CANCEL
    ID_TIMEOUT = -1
    
    DEFAULT_INTERVAL_MS = 250
    DEFAULT_TIMEOUT_MS = 60000
    
    ANIMATED_ICON = os.path.join(RESOURCES_PATH, 'ssx_throbber_animated.gif')
    
    def __init__(self, **kwargs):
        """ Constructor. Standard `wx.Dialog.__init__()` arguments, plus:
        
            @keyword scanFunction: A function, called periodically. Returns
                `None` unless it found what it was scanning for. It should take
                one argument: the `BusyBox` that called it. Non-`None` results
                will be stored in the `result` attribute.
            @keyword interval: The time (in milliseconds) between calls of the
                scanning function.
            @keyword timeout: The time (in milliseconds) before the dialog
                times out and closes.
            @keyword headerText: A string that appears at the top of the dialog.
            @keyword messageText: Smaller text that appears under the header.
            @keyword center: If `True`, center the dialog on the screen.
            @keyword iconFile: The filename of an animated GIF image to show.
        """
        self.result = None
        
        self.scanFunction = kwargs.pop('scanFunction', None)
        self.timeout = kwargs.pop('timeout', self.DEFAULT_TIMEOUT_MS)
        self.interval = kwargs.pop('interval', self.DEFAULT_INTERVAL_MS)
        headerText = kwargs.pop('headerText', "Please Stand By...")
        messageText = kwargs.pop('messageText', "\n"*4)
        center = kwargs.pop('center', True)
        iconFile = kwargs.pop('icon', self.ANIMATED_ICON)
        
        kwargs.setdefault('parent', None)
        kwargs.setdefault('style', wx.CAPTION | wx.CENTRE)
        self.titleText = kwargs.setdefault('title', "Waiting...")
        
        wx.Dialog.__init__(self, **kwargs)
        
        self.SetBackgroundColour("WHITE")

        ani = Animation(iconFile)
        self.throbber = AnimationCtrl(self, -1, ani)
        self.throbber.SetInactiveBitmap(ani.GetFrame(0).ConvertToBitmap())

        self.header = wx.StaticText(self, -1, headerText, size=(400, 40),
                                    style=wx.ALIGN_CENTRE_HORIZONTAL)
        self.header.SetFont(self.GetFont().Bold().Scaled(1.5))
        self.message = wx.StaticText(self, -1, messageText, size=(400, 40),
                                     style=wx.ALIGN_CENTRE_HORIZONTAL)
        
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(wx.Panel(self, -1), 0, wx.EXPAND)
        sizer.Add(self.throbber, 0, wx.ALIGN_CENTER)
        sizer.Add(self.header, 0, wx.ALIGN_CENTER)
        sizer.Add(self.message, 0, wx.ALIGN_CENTER)
        sizer.Add(wx.Panel(self, -1), 1, wx.EXPAND)
        
        b = wx.Button(self, wx.ID_CANCEL)
        sizer.Add(b, 0, wx.EXPAND)
        b.Bind(wx.EVT_BUTTON, self.OnCancel)

        self.lastTime = (self.timeout/1000)
        self.timeoutTime = time.time() + self.lastTime

        self.scanTimer = wx.Timer(self)
        self.timeoutTimer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.OnScanTimer, self.scanTimer)
        self.Bind(wx.EVT_TIMER, self.OnTimeout, self.timeoutTimer)

        self.throbber.Play()
        self.scanTimer.Start(self.interval)
        
        if self.timeout > 0:
            self.timeoutTimer.Start(self.timeout, oneShot=True)

        self.SetSizerAndFit(sizer)
        self.SetSize(400, -1)
        
        if center:
            self.Center()


    #===========================================================================
    # 
    #===========================================================================
    
    def reset(self, headerText=None, messageText=None, interval=None, 
              timeout=None, scanFunction=None, title=None):
        """ Reset the scanner. Various attributes can be changed as well;
            any arguments that are `None` will remain unchanged.
        
            This would (presumably) get called by the scanning function itself,
            e.g. to change from one scan to another.

            @keyword headerText: A string that appears at the top of the dialog.
            @keyword messageText: Smaller text that appears under the header.
            @keyword scanFunction: A function, called periodically.
            @keyword interval: The time (in milliseconds) between calls of the
                scanning function.
            @keyword timeout: The time (in milliseconds) before the dialog
                times out and closes.
        """
        self.scanTimer.Stop()
        self.timeoutTimer.Stop()
        
        self.interval = interval or self.interval
        self.timeout = timeout if timeout is not None else self.timeout
        self.scanFunction = scanFunction or self.scanFunction
        self.titleText = title or self.titleText
        
        self.SetTitle(self.titleText)
        
        if headerText is not None:
            self.header.SetLabel(headerText)
        if messageText is not None:
            self.message.SetLabel(messageText)

        self.lastTime = (self.timeout/1000)
        self.timeoutTime = time.time() + self.lastTime

        self.scanTimer.Start(self.interval)
        
        if self.timeout > 0:
            self.timeoutTimer.Start(self.timeout, oneShot=True)

    
    #===========================================================================
    # 
    #===========================================================================

    def OnScanTimer(self, _evt):
        """ Handle timer triggering the 'scan' function.
        """
        if self.timeout > 0:
            timeLeft = int(self.timeoutTime-time.time())
            if timeLeft < (self.timeout/2000) and timeLeft != self.lastTime:
                self.SetTitle("Waiting %d more seconds..." % timeLeft)
                self.lastTime = timeLeft

        if self.scanFunction:
            result = self.scanFunction(self)
            if result:
                self.timeoutTimer.Stop()
                self.scanTimer.Stop()
                
                self.result = result
                self.EndModal(wx.ID_OK)
    
    
    def OnTimeout(self, _evt):
        """ Handle scan timeout. Closes the dialog with a return value of
            `BusyBox.ID_TIMEOUT`.
        """
        self.scanTimer.Stop()
        self.timeoutTimer.Stop()
        
        self.result = None
        self.EndModal(self.ID_TIMEOUT)
    
    
    def OnCancel(self, evt):
        """ Handle the Cancel button click, doing cleanup before the dialog
            actually cancels.
        """
        self.scanTimer.Stop()
        self.timeoutTimer.Stop()
        self.result = None
        evt.Skip()

    
    #===========================================================================
    # 
    #===========================================================================
    
    @classmethod
    def run(cls, scanFunction=None, headerText="Please Stand By...",
            messageText="", timeout=DEFAULT_TIMEOUT_MS, 
            interval=DEFAULT_INTERVAL_MS, center=True, **kwargs):
        """ Show the dialog and get the results. Keyword arguments other than
            those shown, below, are passed to `wx.Dialog.__init__()`.

            @keyword scanFunction: A function, called periodically. Returns
                `None` unless it found what it was scanning for. It should take
                one argument: the `BusyBox` that called it. Non-`None` results
                will be stored in the `result` attribute.
            @keyword headerText: A string that appears at the top of the dialog.
            @keyword messageText: Smaller text that appears under the header.
            @keyword interval: The time (in milliseconds) between calls of the
                scanning function.
            @keyword timeout: The time (in milliseconds) before the dialog
                times out and closes. Use -1 to run indefinitely.
            @keyword center: If `True`, center the dialog on the screen.
            
            @return: A 2-item tuple containing the ID returned from showing the 
                dialog (`wx.ID_OK`, `wx.ID_CANCEL`, or `BusyBox.ID_TIMEOUT`)
                and the value returned by the scanning function (or `None`). 
        """
        messageText = messageText or ("\n"*4)
        dlg = cls(scanFunction=scanFunction, interval=interval, 
                  timeout=timeout, headerText=headerText, 
                  messageText=messageText, center=center, **kwargs)
        q = dlg.ShowModal()
        result = dlg.result
        
        dlg.throbber.Stop()
        dlg.Destroy()
        return q, result
