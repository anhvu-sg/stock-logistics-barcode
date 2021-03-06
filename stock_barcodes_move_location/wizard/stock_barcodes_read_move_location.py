# Copyright Eficent Business and IT Consulting Services, S.L.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
from odoo import _, fields, models
from odoo.fields import first
from odoo.addons import decimal_precision as dp


class WizStockBarcodesReadMoveLocation(models.TransientModel):
    _name = 'wiz.stock.barcodes.read.move.location'
    _inherit = 'wiz.stock.barcodes.read'
    _description = 'Wizard to read barcode on move location'

    move_location_id = fields.Many2one(
        comodel_name='wiz.stock.move.location',
        string='Move Location',
        readonly=True,
    )
    move_location_qty = fields.Float(
        string='To Move quantities',
        digits=dp.get_precision('Product Unit of Measure'),
        readonly=True,
    )

    def name_get(self):
        return [
            (rec.id, '{} - {}'.format(
                _('Barcode reader'),
                self.env.user.name)) for rec in self]

    def _prepare_move_location_line(self):

        search_args = [
            ('location_id', '=', self.move_location_id.origin_location_id.id),
            ('product_id', '=', self.product_id.id),
        ]
        if self.lot_id:
            search_args.append(('lot_id', '=', self.lot_id.id))
        else:
            search_args.append(('lot_id', '=', False))
        res = self.env['stock.quant'].read_group(search_args, ['quantity'], [])
        max_quantity = res[0]['quantity']
        # Apply the putaway strategy
        move_location_dest_id = self.move_location_id.destination_location_id
        location_dest_id = \
            self.move_location_id.destination_location_id.get_putaway_strategy(
                self.product_id).id or move_location_dest_id.id
        return {
            'move_location_wizard_id': self.move_location_id.id,
            'product_id': self.product_id.id,
            'origin_location_id': self.move_location_id.origin_location_id.id,
            'destination_location_id': location_dest_id,
            'product_uom_id': self.product_id.uom_id.id,
            'move_quantity': self.product_qty,
            'lot_id': self.lot_id.id,
            'max_quantity': max_quantity,
        }

    def _prepare_move_location_line_domain(self, log_scan=False):
        """
        Use the same domain for create or update a stock move location line.
        Source data is scanning log record if undo or wizard model if create or
        update one
        """
        record = log_scan or self
        return [
            ('move_location_wizard_id', '=', self.move_location_id.id),
            ('product_id', '=', record.product_id.id),
            ('lot_id', '=', record.lot_id.id),
        ]

    def _add_move_location_line(self):
        MoveLocationLine = self.env['wiz.stock.move.location.line']
        line = MoveLocationLine.search(
            self._prepare_move_location_line_domain(), limit=1)
        if line:
            line.write({
                'move_quantity': line.move_quantity + self.product_qty,
            })
        else:
            line = MoveLocationLine.create(self._prepare_move_location_line())
        self.move_location_qty = line.move_quantity

    def check_done_conditions(self):
        if self.product_id.tracking != 'none' and not self.lot_id:
            self._set_messagge_info('info', _('Waiting for input lot'))
            return False
        force_add_log = self.env.context.get('force_add_log', False)
        if self.manual_entry and not force_add_log:
            return False
        return super().check_done_conditions()

    def action_done(self):
        result = super().action_done()
        if result:
            self._add_move_location_line()
        return result

    def action_manual_entry(self):
        result = super().action_manual_entry()
        if result:
            self.with_context(force_add_log=True).action_done()
        return result

    def reset_qty(self):
        super().reset_qty()
        self.move_location_qty = 0.0

    def action_undo_last_scan(self):
        res = super().action_undo_last_scan()
        log_scan = first(self.scan_log_ids.filtered(
            lambda x: x.create_uid == self.env.user))
        if log_scan:
            move_location_line = self.env['wiz.stock.move.location.line'].search(
                self._prepare_move_location_line_domain(log_scan=log_scan))
            if move_location_line:
                qty = move_location_line.move_quantity - log_scan.product_qty
                move_location_line.move_quantity = max(qty, 0.0)
                self.move_location_qty = move_location_line.move_quantity
        log_scan.unlink()
        return res

    def action_confirm(self):
        return {'type': 'ir.actions.act_window_close'}
