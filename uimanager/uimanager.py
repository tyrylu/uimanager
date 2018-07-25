import re
import logging
import wx
import wx.xrc as xrc
from . import uimgr

class Holder: pass

def get():
    return uimgr

log = logging.getLogger(__name__)
class UIManager(object):
    def __init__(self, resource_file, top_level_name, top_level_type="frame", reuse_app=False, load_on=None):
        global uimgr
        self._event_aliases = {}
        self._menu_items = {}
        self._menu_items_by_name = {}
        self._menus = {}
        self.resource_name = resource_file
        self.resource_names = get_xrc_names(self.resource_name)
        if not reuse_app:
            self.app = wx.App(redirect=False)
        else:
            self.app = wx.GetApp()
        self.resource = xrc.XmlResource(resource_file)
        self.top_level = getattr(self, "get_%s"%top_level_type)(top_level_name, load_on)
        self.app.TopLevelWindow = self.top_level
        self.add_event_alias("button", "clicked")
        self.add_event_alias("menu", "selected")
        self._dlg_stack = []
        self.current_dialog = None
        uimgr = self

    def get_frame(self, name, load_on=None):
        if load_on:
            self.resource.LoadFrame(load_on, getattr(self, "top_level", None), name)
            return load_on
        else:
            return self.resource.LoadFrame(getattr(self, "top_level", None), name)

    def get_dialog(self, name, load_on=None):
        if load_on:
            self.resource.LoadDialog(load_on, self.usable_parent, name)
            return load_on
        else:
            return self.resource.LoadDialog(self.usable_parent, name)
    
    def auto_bind(self, parent, eventsobj, only=[], alternate_bind_of=[]):
        if eventsobj is None: return
        handlers = [name for name in dir(eventsobj) if name.startswith("on_")]
        olen = len(only)
        for h in handlers:
            name = find_xrc_name(h, self.resource_names)
            if not name:
                log.warning(f"The handler {h} did not correspond to any of the names in the xrc file.")
                continue
            name_and_event = h[3:]
            event = name_and_event.replace(name + "_", "")
            if olen != 0 and name not in only: continue
            event = self._lookup_event(event)
            parent.Bind(event, getattr(eventsobj, h), id=xrc.XRCID(name))
        for a in alternate_bind_of: self._alternate_bind(parent, a, eventsobj)

    def run(self, show=True):
        if show: self.top_level.Show()
        self.app.MainLoop()

    def close(self):
        if self.usable_parent:
            self.top_level.Close()
        self.app.ExitMainLoop()

    def add_event_alias(self, wx_event, event):
        self._event_aliases[event] = wx_event

    def show_error(self, title, message):
        wx.MessageBox(message, title, parent=self.current_dialog or self.top_level, style=wx.ICON_ERROR|wx.OK)

    def get_values(self, parent, *vals):
        ret = Holder()
        for name in vals:
            try:
                setattr(ret, name, parent.FindWindowByName(name).Value)
            except AttributeError:
                setattr(ret, name, parent.FindWindowByName(name).Selection)
                return ret
    
    def set_values(self, parent, valsobj, *vals):
        for name in vals:
            try:
                parent.FindWindowByName(name).Value = unicode(getattr(valsobj, name, ""))
            except AttributeError:
                parent.FindWindowByName(name).Selection = getattr(valsobj, name)
   
    def clear_fields(self, parent, *fields):
        for f in fields:
            parent.FindWindowByName(f).Value = ""

    def show_dialog(self, name, eventsobj=None, only=[], alternate_bind_of=[]):
        dlg = self.prepare_show_dialog(name, eventsobj, only, alternate_bind_of)
        dlg.ShowModal()

    def prepare_show_dialog(self, name, eventsobj=None, only=[], alternate_bind_of=[]):
        dlg = self.get_dialog(name)
        if self.current_dialog is not None:
            dlg.Bind(wx.EVT_CLOSE, self._unwind_stack)
        self._dlg_stack.append(dlg)
        self.current_dialog = dlg
        if eventsobj:
            self.auto_bind(self.current_dialog, eventsobj, only, alternate_bind_of)
        else: # The subclassing case
            self.auto_bind(self.current_dialog, self.current_dialog, only, alternate_bind_of)
        #Hack to make wxgtk's focus strangeness happy
        #Sets focus to the first non statictext widget of the panel which must be there, so we don't care... It could go wrong though in the future.
        for c in self.current_dialog.Children[0].Children:
            if not isinstance(c, wx.StaticText):
                c.SetFocus()
                break
        return dlg

    def prepare_xrc_dialog(self, cls, alternate_bind_of=[], parent=None, **post_init_kwargs):
        if not parent: parent = self.top_level
        inst = cls()
        if hasattr(wx, "PreDialog"):
            pre = wx.PreDialog()
            self.resource.LoadOnDialog(pre, parent, cls.xrc_name)
            inst.PostCreate(pre)
        else: # Phoenix
            self.resource.LoadDialog(inst, parent, cls.xrc_name)
        self.auto_bind(inst, inst, alternate_bind_of=alternate_bind_of)
        if hasattr(inst, "post_init"): inst.post_init(**post_init_kwargs)
        return inst

    def prepare_xrc_frame(self, cls, alternate_bind_of=[], parent=None, **post_init_kwargs):
        if not parent: parent = self.top_level
        inst = cls()
        if hasattr(wx, "PreFrame"):
            pre = wx.PreFrame()
            self.resource.LoadOnFrame(pre, parent, cls.xrc_name)
            inst.PostCreate(pre)
        else: # Phoenix
            self.resource.LoadFrame(inst, parent, cls.xrc_name)
        self.auto_bind(inst, inst, alternate_bind_of=alternate_bind_of)
        if hasattr(inst, "post_init"): inst.post_init(**post_init_kwargs)
        return inst
        
    def _unwind_stack(self, evt):
        try: self._dlg_stack.remove(self.current_dialog)
        except ValueError: pass
        try: self.current_dialog = self._dlg_stack.pop()
        except IndexError: self.current_dialog = None
        evt.Skip()

    def _alternate_bind(self, parent, meth, evtobj):
        _on, name, event = meth.split("_", 2)
        evt = self._lookup_event(event)
        parent.FindWindowByName(name).Bind(evt, getattr(evtobj, meth))

    def _lookup_event(self, evt):
        if not hasattr(wx, "EVT_%s"%evt.upper()):
            evt = self._event_aliases[evt]
        return getattr(wx, "EVT_%s"%evt.upper())

    @property
    def usable_parent(self):
        obj = getattr(self, "top_level", None)
        if not issubclass(obj.__class__, wx.Window): return None
        return obj

    def _menu_item_callables(self, source):
        for member_name in source.__class__.__dict__.keys():
            member_obj = getattr(source, member_name)
            if hasattr(member_obj, "item_label"):
                yield member_obj

    def register_menu_commands(self, source):
        for cmd in self._menu_item_callables(source):
            menu_path = cmd.menu.split("/")
            menu = self._ensure_menu(menu_path)
            item_id = wx.NewId()
            label = cmd.item_label
            if cmd.item_shortcut:
                label += "\t%s"%cmd.item_shortcut
            item = menu.Append(item_id, label)
            self.top_level.Bind(wx.EVT_MENU, cmd, id=item_id)
            self._menu_items[(cmd.menu, cmd.item_label)] = item
            if cmd.item_name:
                self._menu_items_by_name[cmd.item_name] = item
    
    def _ensure_menu(self, path, parent=None):
        if not path:
            return parent
        component = path.pop(0)
        if not parent:
            pos = self.top_level.MenuBar.FindMenu(component)
            if  pos != -1:
                return self._ensure_menu(path, self.top_level.MenuBar.GetMenu(pos))
            else:
                menu = wx.Menu()
                self.top_level.MenuBar.Append(menu, component)
                return self._ensure_menu(path, menu)
        else:
            menu = None
            for item in parent.MenuItems:
                if item.ItemLabelText == component:
                    menu = item.SubMenu
                    break
            if menu:
                return self._ensure_menu(path, menu)
            else:
                menu = wx.Menu()
                menu_id = wx.NewId()
                parent.Append(menu_id, component, menu)
                self._menus[menu] = menu_id
                return self._ensure_menu(path, menu)

    def unregister_menu_commands(self, source):
        for cmd in self._menu_item_callables(source):
            item = self._menu_items[(cmd.menu, cmd.item_label)]
            menu = item.Menu
            menu.RemoveItem(item)
            parent = menu.Parent
            while parent:
                if menu.MenuItemCount == 0:
                    menu_id = self._menus.pop(menu)
                    parent.Destroy(menu_id)
                menu = parent
                parent = menu.Parent
            if menu.MenuItemCount == 0: # We can remove it from the main menubar
                self.top_level.MenuBar.Remove(self.top_level.MenuBar.FindMenu(menu.Label))

    def menu_item_with_name(self, name):
        return self._menu_items_by_name[name]


def menu_command(menu, label, shortcut, name=None):
    def wrap(func):
        func.menu = menu
        func.item_label = label
        func.item_shortcut = shortcut
        func.item_name = name
        return func
    return wrap

def get_xrc_names(fname):
    names = set()
    with open(fname, "r", encoding="utf-8") as fp:
        for line in fp:
            match = re.search(r'name=\"(.*)\"', line)
            if match:
                names.add(match.group(1))
    return names

def find_xrc_name(meth_name, names):
    candidates = []
    meth_name_without_prefix = meth_name[3:]
    for name in names:
        if meth_name_without_prefix.startswith(name):
            candidates.append(name)
    if not candidates:
        return None
    result = candidates[0]
    for candidate in candidates[1:]:
        if len(candidate) > len(result):
            result = candidate
    return result
