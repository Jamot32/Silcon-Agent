`default_nettype none

module traffic_light #(
    parameter GREEN_CYCLES = 4,
    parameter YELLOW_CYCLES = 2,
    parameter RED_CYCLES = 3,
    parameter WALK_CYCLES = 3
) (
    input wire clk,
    input wire rst_n,
    input wire ped_request,
    output reg green,
    output reg yellow,
    output reg red,
    output reg walk
);
    localparam [1:0] GREEN = 2'd0, YELLOW = 2'd1, RED = 2'd2, WALK = 2'd3;
    localparam [7:0] GREEN_LAST = GREEN_CYCLES[7:0] - 8'd1;
    localparam [7:0] YELLOW_LAST = YELLOW_CYCLES[7:0] - 8'd1;
    localparam [7:0] RED_LAST = RED_CYCLES[7:0] - 8'd1;
    localparam [7:0] WALK_LAST = WALK_CYCLES[7:0] - 8'd1;
    reg [1:0] state;
    reg [7:0] elapsed;
    reg pending;
    reg previous_request;
    wire request_edge = ped_request && !previous_request;

    always @(posedge clk) begin
        if (!rst_n) begin
            state <= RED;
            elapsed <= 8'd0;
            pending <= 1'b0;
            previous_request <= 1'b0;
        end else begin
            previous_request <= ped_request;
            if (request_edge && state != WALK)
                pending <= 1'b1;
            case (state)
                GREEN: begin
                    if (elapsed == GREEN_LAST) begin
                        state <= YELLOW;
                        elapsed <= 8'd0;
                    end else
                        elapsed <= elapsed + 8'd1;
                end
                YELLOW: begin
                    if (elapsed == YELLOW_LAST) begin
                        state <= RED;
                        elapsed <= 8'd0;
                    end else
                        elapsed <= elapsed + 8'd1;
                end
                RED: begin
                    if (elapsed == RED_LAST) begin
                        elapsed <= 8'd0;
                        if (pending || request_edge) begin
                            state <= WALK;
                            pending <= 1'b0;
                        end else
                            state <= GREEN;
                    end else
                        elapsed <= elapsed + 8'd1;
                end
                WALK: begin
                    if (elapsed == WALK_LAST) begin
                        state <= RED;
                        elapsed <= 8'd0;
                    end else
                        elapsed <= elapsed + 8'd1;
                end
                default: begin
                    state <= RED;
                    elapsed <= 8'd0;
                    pending <= 1'b0;
                end
            endcase
        end
    end

    always @* begin
        green = 1'b0;
        yellow = 1'b0;
        red = 1'b1;
        walk = 1'b0;
        case (state)
            GREEN: begin
                green = 1'b1;
                red = 1'b0;
            end
            YELLOW: begin
                yellow = 1'b1;
                red = 1'b0;
            end
            WALK: walk = 1'b1;
            default: begin
                green = 1'b0;
                yellow = 1'b0;
                red = 1'b1;
                walk = 1'b0;
            end
        endcase
    end
endmodule

`default_nettype wire
